# Student verifikacija bot - upute za postavljanje

Bot radi ovako:

1. Novi član vidi samo kanal **#verifikacija** s dva gumba: *Da, student sam* / *Ne, nisam student*.
2. **Ne** (uz dodatnu potvrdu) → korisnik dobiva **ban** (može se promijeniti u kick, vidi `.env`).
3. **Da** → upiše ime, prezime i **broj osobne iskaznice** → bot ga u DM-u traži **potvrdu o statusu studenta s e-Građana** (PDF ili slika).
4. Sve stiže u **privatni kanal za pregled** (samo staff). Staff klikne **Odobri** ili **Odbij** (uz opcionalni razlog).
5. Odobreno → korisnik dobiva rolu **Student** i otključavaju mu se svi ostali kanali. Potvrdu i broj osobne bot nakon odluke briše iz kanala.

---

## 1. Discord bot (Developer Portal)

1. https://discord.com/developers/applications → **New Application**.
2. Lijevo **Bot** → **Reset Token** → kopiraj token (to je `DISCORD_TOKEN`; nikome ga ne daj).
3. Na istoj stranici u *Privileged Gateway Intents* uključi **Server Members Intent**. (Ostalo ne treba.)
4. **OAuth2 → URL Generator**: scope `bot` + `applications.commands`; ovlasti:
   *View Channels, Send Messages, Embed Links, Attach Files, Read Message History, Manage Roles, Ban Members, Kick Members*.
5. Otvori generirani link i dodaj bota na server.

## 2. Rola i kanali na serveru

Uključi *Settings → Advanced → Developer Mode* (da možeš kopirati ID-eve).

**Role**
- Napravi rolu **Student**.
- U *Server Settings → Roles* povuci rolu **bota IZNAD role Student**. Inače je ne može dodjeljivati.
- Bot ne može banati ni dirati korisnike s višom rolom od svoje (npr. admine/vlasnika).
- Staff koji pregledava treba ovlast **Manage Roles** (ili Administrator).

**Kanali i dozvole**

| Kanal | @everyone | Student | Staff |
|---|---|---|---|
| **#verifikacija** | Vidi kanal, **ne može pisati** | **Ne vidi** (skriveno) | vidi |
| **#verifikacija-pregled** (privatni) | ne vidi | ne vidi | vidi + piše |
| **svi ostali kanali / kategorije** | **ne vidi** (View Channel ✗) | **vidi** (View Channel ✓) | vidi |

Bot mora imati pristup i #verifikacija (slanje poruka) i #verifikacija-pregled (slanje poruka + privitaka).

## 3. Postavke (`.env`)

```
cp .env.example .env
```

Otvori `.env` i popuni (desni klik → *Copy ID*):

| Varijabla | Što je |
|---|---|
| `DISCORD_TOKEN` | token bota iz koraka 1 |
| `GUILD_ID` | ID servera (desni klik na ikonu servera) |
| `STUDENT_ROLE_ID` | ID role Student |
| `VERIFY_CHANNEL_ID` | ID kanala #verifikacija |
| `REVIEW_CHANNEL_ID` | ID privatnog kanala za pregled |
| `NON_STUDENT_ACTION` | `ban` (zadano) ili `kick` |
| `DELETE_DOCS_AFTER_REVIEW` | `true` (zadano) - briše slike nakon odluke |

Bez razmaka oko `=`, bez navodnika. **`.env` se ne smije dijeliti ni stavljati na GitHub.**

## 4. Pokretanje (potreban Docker)

```
docker compose up -d --build     # pokreni
docker compose logs -f           # log; treba pisati "Bot spreman kao ..."
docker compose restart           # nakon izmjene .env
docker compose down              # zaustavi
```

Baza (`data/bot.db`) sprema samo ID korisnika, ime/prezime i status zahtjeva (broj osobne se ne sprema, vidljiv je samo staffu u zahtjevu dok se ne odluči); ostaje u mapi `data/` i preživljava restart.

## 5. Aktivacija

U kanalu **#verifikacija** (ili bilo gdje) upiši `/setup_verifikacija` (vidljivo samo adminima). Bot objavi poruku s gumbima u kanal iz `VERIFY_CHANNEL_ID`. Radi se jednom; gumbi rade i nakon restarta.

## 6. Testiranje prije puštanja

Uđi na server drugim računom i prođi cijeli tok. **Za "Ne" koristi testni račun** - bit će banan (unban: *Server Settings → Bans*).
Provjeri: DM stiže, potvrda i broj osobne se pojave u pregled kanalu, Odobri daje rolu, Odbij šalje poruku korisniku.

## Česti problemi

- **Gumbi/komanda se ne pojavljuju** - provjeri `GUILD_ID` i da je bot pozvan sa scope-om `applications.commands`.
- **"Ne mogu ti poslati DM"** - korisnik mora dopustiti DM od članova servera.
- **"Nisam uspio dodati rolu" / ban ne radi** - rola bota nije iznad role Student (odnosno korisnika), ili botu fali ovlast.
- **Bot ne vidi nove članove** - nije uključen Server Members Intent.
- **Greška pri pokretanju s KeyError** - nedostaje varijabla u `.env`.

## Privatnost (važno)

Osobna iskaznica je osjetljiv osobni podatak (GDPR). Preporuka:
- upišite u pravila servera zašto se dokumenti traže i tko ih vidi;
- pregled kanal neka vidi samo nekoliko ljudi, a slike **ne preuzimajte** ni ne dijelite;
- korisniku je u DM-u rečeno da može prekriti OIB i osjetljive podatke; bitni su ime, prezime i status studenta; staff neka broj osobne usporedi s potvrdom i ne kopira ga nigdje;
- ostavite `DELETE_DOCS_AFTER_REVIEW=true`, tako da bot nakon odluke briše slike iz kanala.
