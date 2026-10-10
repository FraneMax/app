"""Discord bot za verifikaciju studenata (rucni pregled dokumenata).

Tok:
1. Novi clan vidi samo #verifikacija s gumbima "Da, student sam" / "Ne, nisam student".
2. "Ne" (uz potvrdu) -> ban (ili kick, vidi NON_STUDENT_ACTION).
3. "Da" -> ime i prezime -> broj osobne -> bot u DM-u trazi potvrdu s e-Gradjana.
4. Sve stize u privatni REVIEW kanal gdje staff klikne Odobri / Odbij.
5. Odobreno -> rola Student (otkljucava ostale kanale).
"""
import asyncio
import datetime
import io
import os
import sqlite3

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["GUILD_ID"])
STUDENT_ROLE_ID = int(os.environ["STUDENT_ROLE_ID"])
VERIFY_CHANNEL_ID = int(os.environ["VERIFY_CHANNEL_ID"])
REVIEW_CHANNEL_ID = int(os.environ["REVIEW_CHANNEL_ID"])
NON_STUDENT_ACTION = os.getenv("NON_STUDENT_ACTION", "ban").lower()
DELETE_DOCS = os.getenv("DELETE_DOCS_AFTER_REVIEW", "true").lower() == "true"
DATA_DIR = os.getenv("DATA_DIR", "/data")

ID_FIELD = "Broj osobne iskaznice"
MAX_FILE_BYTES = 8 * 1024 * 1024
UPLOAD_TIMEOUT = 600  # sekundi po dokumentu
GUILD = discord.Object(GUILD_ID)

os.makedirs(DATA_DIR, exist_ok=True)
db = sqlite3.connect(os.path.join(DATA_DIR, "bot.db"))
db.execute(
    """CREATE TABLE IF NOT EXISTS requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        first_name TEXT, last_name TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        review_msg_id INTEGER,
        decided_by INTEGER,
        created TEXT, decided TEXT)"""
)
db.commit()

intents = discord.Intents.default()
intents.members = True  # Server Members Intent (ukljuci u Developer Portalu)


class StudentBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(VerifyView())
        self.add_view(ReviewView())
        self.tree.copy_global_to(guild=GUILD)
        await self.tree.sync(guild=GUILD)


client = StudentBot()
active: set[int] = set()  # korisnici koji trenutno salju dokumente


def now():
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def has_student_role(member) -> bool:
    return any(r.id == STUDENT_ROLE_ID for r in getattr(member, "roles", []))


def pending_request(user_id):
    return db.execute(
        "SELECT id FROM requests WHERE user_id=? AND status='pending'", (user_id,)
    ).fetchone()


async def review_channel():
    return client.get_channel(REVIEW_CHANNEL_ID) or await client.fetch_channel(REVIEW_CHANNEL_ID)


# ---------------------------------------------------------------- dolazak
@client.event
async def on_ready():
    print(f"Bot spreman kao {client.user}")


@client.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return
    try:
        await member.send(
            f"Dobrodošao/la na **{member.guild.name}**! Za pristup serveru otvori kanal "
            f"<#{VERIFY_CHANNEL_ID}> i odgovori jesi li student."
        )
    except discord.HTTPException:
        pass  # DM-ovi zatvoreni, korisnik ce svejedno vidjeti kanal


# ---------------------------------------------------------------- gumbi Da/Ne
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Da, student sam", style=discord.ButtonStyle.success, custom_id="verify:yes")
    async def yes(self, i: discord.Interaction, _):
        if has_student_role(i.user):
            return await i.response.send_message("Već si verificiran/a.", ephemeral=True)
        if pending_request(i.user.id):
            return await i.response.send_message(
                "Tvoj zahtjev je već poslan i čeka pregled. Javit ćemo ti se u DM.", ephemeral=True)
        if i.user.id in active:
            return await i.response.send_message(
                "Već je u tijeku slanje dokumenata - provjeri DM.", ephemeral=True)
        await i.response.send_modal(NameModal())

    @discord.ui.button(label="Ne, nisam student", style=discord.ButtonStyle.danger, custom_id="verify:no")
    async def no(self, i: discord.Interaction, _):
        if has_student_role(i.user):
            return await i.response.send_message("Već si verificiran/a.", ephemeral=True)
        action = "banan" if NON_STUDENT_ACTION == "ban" else "izbačen"
        await i.response.send_message(
            f"Ovaj server je samo za studente. Ako potvrdiš, bit ćeš **{action}** sa servera. "
            "Jesi li siguran/na?",
            view=ConfirmNo(), ephemeral=True)


class ConfirmNo(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Potvrđujem, nisam student", style=discord.ButtonStyle.danger)
    async def confirm(self, i: discord.Interaction, _):
        await i.response.edit_message(content="Hvala na iskrenosti. Doviđenja!", view=None)
        member = i.user
        reason = "Korisnik je potvrdio da nije student"
        try:
            await member.send(f"Ovaj server je samo za studente pa te uklanjamo. ({reason})")
        except discord.HTTPException:
            pass
        try:
            if NON_STUDENT_ACTION == "kick":
                await i.guild.kick(member, reason=reason)
            else:
                await i.guild.ban(member, reason=reason, delete_message_seconds=0)
        except discord.HTTPException as e:
            ch = await review_channel()
            await ch.send(f"⚠️ Nisam uspio ukloniti {member.mention} ({e}). Provjeri hijerarhiju rola i ovlasti bota.")

    @discord.ui.button(label="Odustani", style=discord.ButtonStyle.secondary)
    async def cancel(self, i: discord.Interaction, _):
        await i.response.edit_message(content="U redu, ništa se nije dogodilo.", view=None)


# ---------------------------------------------------------------- ime i dokumenti
class NameModal(discord.ui.Modal, title="Verifikacija studenta"):
    first = discord.ui.TextInput(label="Ime", max_length=50)
    last = discord.ui.TextInput(label="Prezime", max_length=50)
    id_number = discord.ui.TextInput(label="Broj osobne iskaznice", min_length=6, max_length=20)

    async def on_submit(self, i: discord.Interaction):
        user = i.user
        id_number = self.id_number.value.strip().replace(" ", "")
        if not id_number.isalnum():
            return await i.response.send_message(
                "Broj osobne smije sadržavati samo slova i brojke.", ephemeral=True)
        try:
            await user.send(
                "Bok! Još mi treba **potvrda o statusu studenta s e-Građana** "
                "(PDF ili slika/screenshot).")
        except discord.HTTPException:
            return await i.response.send_message(
                "Ne mogu ti poslati DM. Uključi *Server → Privacy Settings → Direct Messages* "
                "pa klikni gumb ponovno.", ephemeral=True)
        await i.response.send_message("Poslao sam ti DM - nastavi tamo.", ephemeral=True)
        asyncio.create_task(
            collect_documents(user, self.first.value.strip(), self.last.value.strip(), id_number))


STEPS = [
    ("potvrda", "🎓 Pošalji **potvrdu o statusu studenta s e-Građana** (PDF ili slika/screenshot). "
                "Na njoj mora biti vidljivo tvoje ime i prezime te da si student."),
]
HINT = ("\nMožeš prekriti OIB i ostale osjetljive podatke - bitni su ime, prezime i status studenta. "
        "Pošalji kao **privitak** u ovom razgovoru. Imaš 10 minuta.")


async def ask_file(user: discord.User, prompt: str):
    await user.send(prompt + HINT)

    def check(m: discord.Message):
        return m.author.id == user.id and m.guild is None and m.attachments

    for _ in range(3):
        msg = await client.wait_for("message", check=check, timeout=UPLOAD_TIMEOUT)
        a = msg.attachments[0]
        ok_type = (a.content_type or "").startswith("image/") or a.content_type == "application/pdf"
        if ok_type and a.size <= MAX_FILE_BYTES:
            ext = os.path.splitext(a.filename)[1].lower() or ".jpg"
            return ext, await a.read()
        await user.send("Datoteka mora biti slika ili PDF, najviše 8 MB. Pokušaj ponovno.")
    raise ValueError("previše neispravnih pokušaja")


async def collect_documents(user: discord.User, first: str, last: str, id_number: str):
    active.add(user.id)
    try:
        files = []
        for key, prompt in STEPS:
            ext, data = await ask_file(user, prompt)
            files.append((f"{key}{ext}", data))

        cur = db.execute(
            "INSERT INTO requests(user_id, first_name, last_name, created) VALUES(?,?,?,?)",
            (user.id, first, last, now()))
        db.commit()
        req_id = cur.lastrowid

        guild = client.get_guild(GUILD_ID)
        member = guild.get_member(user.id)
        embed = discord.Embed(title=f"Zahtjev za verifikaciju #{req_id}", color=discord.Color.orange())
        embed.add_field(name="Korisnik", value=f"{user.mention}\n`{user.id}`")
        embed.add_field(name="Ime i prezime", value=f"{first} {last}")
        embed.add_field(name=ID_FIELD, value=f"`{id_number}`")
        embed.add_field(name="Discord račun od", value=discord.utils.format_dt(user.created_at, "R"))
        if member and member.joined_at:
            embed.add_field(name="Na serveru od", value=discord.utils.format_dt(member.joined_at, "R"))
        embed.set_footer(text="Priloženo: potvrda s e-Građana. Provjeri da se ime i prezime podudaraju.")

        ch = await review_channel()
        msg = await ch.send(
            embed=embed,
            files=[discord.File(io.BytesIO(d), filename=n) for n, d in files],
            view=ReviewView())
        db.execute("UPDATE requests SET review_msg_id=? WHERE id=?", (msg.id, req_id))
        db.commit()
        await user.send("✅ Sve je poslano. Naš tim će pregledati dokumente, javit ćemo ti se ovdje.")
    except asyncio.TimeoutError:
        await user.send("⌛ Isteklo je vrijeme. Klikni gumb u verifikacijskom kanalu da počneš ispočetka.")
    except Exception as e:  # noqa: BLE001
        print("Greška kod prikupljanja dokumenata:", repr(e))
        try:
            await user.send("Dogodila se greška. Pokušaj ponovno ili kontaktiraj admina.")
        except discord.HTTPException:
            pass
    finally:
        active.discard(user.id)


# ---------------------------------------------------------------- pregled (staff)
def staff_allowed(member) -> bool:
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.manage_roles or perms.administrator))


async def finalize(i: discord.Interaction, row, approved: bool, reason: str | None = None):
    req_id, user_id = row["id"], row["user_id"]
    changed = db.execute(
        "UPDATE requests SET status=?, decided_by=?, decided=? WHERE id=? AND status='pending'",
        ("approved" if approved else "rejected", i.user.id, now(), req_id)).rowcount
    db.commit()
    if not changed:
        return await i.response.send_message("Ovaj zahtjev je već obrađen.", ephemeral=True)

    guild = i.guild
    member = guild.get_member(user_id)
    note = ""
    if approved:
        if member:
            try:
                await member.add_roles(guild.get_role(STUDENT_ROLE_ID), reason=f"Verificirao {i.user}")
            except discord.HTTPException as e:
                note = f"\n⚠️ Nisam uspio dodati rolu: {e}"
        else:
            note = "\n⚠️ Korisnik je napustio server."

    embed = i.message.embeds[0].copy()
    for idx, f in enumerate(embed.fields):
        if f.name == ID_FIELD:
            embed.remove_field(idx)  # broj osobne se ne cuva nakon odluke
            break
    embed.color = discord.Color.green() if approved else discord.Color.red()
    embed.title = f"Zahtjev #{req_id} - {'ODOBREN' if approved else 'ODBIJEN'}"
    embed.add_field(name="Odlučio", value=i.user.mention, inline=False)
    if reason:
        embed.add_field(name="Razlog", value=reason[:500], inline=False)
    if DELETE_DOCS:
        embed.set_footer(text="Dokumenti su obrisani nakon odluke.")
    kwargs = {"attachments": []} if DELETE_DOCS else {}
    await i.response.edit_message(embed=embed, view=None, **kwargs)
    if note:
        await i.followup.send(note, ephemeral=True)

    if member:
        try:
            if approved:
                await member.send("🎉 Verifikacija je odobrena! Sada imaš pristup svim kanalima.")
            else:
                extra = f"\nRazlog: {reason}" if reason else ""
                await member.send("❌ Zahtjev nije odobren." + extra +
                                  "\nMožeš pokušati ponovno klikom na gumb u verifikacijskom kanalu.")
        except discord.HTTPException:
            pass


def row_for_message(message_id):
    cur = db.execute("SELECT id, user_id, status FROM requests WHERE review_msg_id=?", (message_id,))
    r = cur.fetchone()
    return {"id": r[0], "user_id": r[1], "status": r[2]} if r else None


class RejectModal(discord.ui.Modal, title="Odbij zahtjev"):
    reason = discord.ui.TextInput(
        label="Razlog (korisnik će ga vidjeti)", required=False, max_length=300,
        style=discord.TextStyle.paragraph)

    def __init__(self, row):
        super().__init__()
        self.row = row

    async def on_submit(self, i: discord.Interaction):
        await finalize(i, self.row, False, self.reason.value or None)


class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _row(self, i: discord.Interaction):
        if not staff_allowed(i.user):
            await i.response.send_message("Nemaš ovlasti za ovo.", ephemeral=True)
            return None
        row = row_for_message(i.message.id)
        if not row or row["status"] != "pending":
            await i.response.send_message("Zahtjev je već obrađen ili ne postoji.", ephemeral=True)
            return None
        return row

    @discord.ui.button(label="Odobri", style=discord.ButtonStyle.success, custom_id="review:approve")
    async def approve(self, i: discord.Interaction, _):
        if row := await self._row(i):
            await finalize(i, row, True)

    @discord.ui.button(label="Odbij", style=discord.ButtonStyle.danger, custom_id="review:reject")
    async def reject(self, i: discord.Interaction, _):
        if row := await self._row(i):
            await i.response.send_modal(RejectModal(row))


# ---------------------------------------------------------------- admin komanda
@client.tree.command(name="setup_verifikacija", description="Objavi poruku s gumbima u verifikacijski kanal")
@app_commands.default_permissions(administrator=True)
async def setup_cmd(i: discord.Interaction):
    ch = client.get_channel(VERIFY_CHANNEL_ID) or await client.fetch_channel(VERIFY_CHANNEL_ID)
    embed = discord.Embed(
        title="Dobrodošao/la! Verifikacija studenata",
        description=("Ovaj server je namijenjen **studentima**.\n\n"
                     "• Ako si student, klikni **Da** i unesi ime, prezime i broj osobne iskaznice. Zatim ćemo te u DM-u zatražiti "
                     "**potvrdu o statusu studenta s e-Građana**. Podatke pregledava samo staff, a nakon odluke se brišu.\n"
                     "• Ako nisi student, klikni **Ne** - nećeš moći ostati na serveru."),
        color=discord.Color.blurple())
    await ch.send(embed=embed, view=VerifyView())
    await i.response.send_message(f"Poruka objavljena u {ch.mention}.", ephemeral=True)


client.run(TOKEN)
