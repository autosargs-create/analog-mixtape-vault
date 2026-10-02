# 📼 Analog Mixtape Vault

Tīmekļa aplikācija kasešu, vinila plašu un lenšu analogās kolekcijas uzskaitei, viedajai meklēšanai un pasūtījuma miksteipu (Mixtape) veidošanai ar precīzu kasetes taimingu un meistara ieraksta ceļvedi.

---

## 🚀 Kā palaist lokāli (izstrāde / tests):

Aplikācija pašlaik jau ir palaista un pieejama Tavā pārlūkā:
👉 **http://localhost:8090** (vai no telefona lokālajā Wi-Fi: `http://<TAVA_DATORA_IP>:8090`)

Ja vēlies palaist manuāli ar Python:
```bash
cd /home/jonyz/Work/analog-mixtape-vault
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8090
```

---

## 🐳 Izvietošana kā 5. serviss uz Orange Pi Zero 3 (Docker):

Uz Orange Pi Zero 3 vienkārši pārkopē šo mapi `analog-mixtape-vault` un palaid ar vienu komandu:

```bash
cd analog-mixtape-vault
docker compose up -d --build
```

### Kā iekļaut esošajā `docker-compose.yml` (ja visi 4 servisi ir vienā failā):
Pievieno šo servisa bloku savam esošajam failam:

```yaml
  analog-vault:
    build: ./analog-mixtape-vault
    container_name: analog-vault
    restart: unless-stopped
    ports:
      - "8090:8090"
    volumes:
      - ./analog-mixtape-vault/data:/app/data
    environment:
      - DATA_DIR=/app/data
```

---

## 🌐 Piekļuve caur Cloudflare Tunnel (Bezmaksas HTTPS draugiem):

Tā kā Tev jau ir domēns Cloudflare, uz Orange Pi atliek palaist tuneli:

1. Ja `cloudflared` jau ir uzinstalēts vai griežas kā konteiners, pievieno jaunu Ingress noteikumu:
   ```yaml
   ingress:
     - hostname: kasetes.tavsdomens.lv
       service: http://localhost:8090
     - service: http_status:404
   ```
2. Vai caur Cloudflare Zero Trust tīmekļa paneli:
   * **Tunnels** ➔ Izvēlies savu Orange Pi tuneli.
   * Pievieno **Public Hostname**:
     * Subdomain: `kasetes` (vai `mixtape`)
     * Domain: `tavsdomens.lv`
     * Type: `HTTP`
     * URL: `localhost:8090` (vai `analog-vault:8090`, ja ir tajā pašā docker tīklā).

Gatavs! Draugi no jebkuras vietas pasaulē varēs atvērt `https://kasetes.tavsdomens.lv`, meklēt dziesmas un salikt savus miksteipus.

---

## 🎛️ Galvenās funkcijas:
1. **🔒 Drošības Vārti & Piekļuves Pārvaldība:**
   - **Slēgta lapa (Gatekeeper):** Svešinieki un roboti redz tikai paroles ievades lauku. Nekādi kasešu dati vai saraksti netiek atklāti bez autorizācijas.
   - **Anti-Bruteforce:** Pēc 5 neveiksmīgiem minēšanas mēģinājumiem IP adrese tiek nobloķēta uz 60 sekundēm.
   - **Meistara PIN (Noklusējums `1987`):** Pilna piekļuve skanēšanai, katalogam, kasešu koferu vietām, pasūtījumiem un paroles pārvaldībai. PIN var jebkurā brīdī nomainīt cilnē „🔑 Piekļuves”.
   - **Draugu Piekļuves Paroles:** Izveido personīgu paroli katram draugam (piemēram, `peteris-tape` vai `rock-521`). Draugi redz tikai meklēšanu un miksteipu veidošanu (bez privātajām piezīmēm un glabāšanas plauktiem). Kad pasākums beidzies, paroli ar vienu klikšķi var atslēgt vai dzēst. Kad paroles nav aktīvas — lapai var piekļūt tikai pats Meistars.
2. **Katalogs & Zibenīga meklēšana:** Atrodi jebkuru izpildītāju vai dziesmu sekundes simtdaļā, redzi fizisko kasetes numuru (`MC-0001`) un glabāšanas vietu (`Koferis 1`).
3. **AI Vision & Tiešsaistes Skanēšana:** Nofotografē kaseti ar telefonu — Google Gemini AI vai vietējais OCR + iTunes bāze automātiski nolasa izpildītāju, albumu un precīzus dziesmu garumus.
4. **Tiešsaistes Taiminga Monitors:** Lapas augšpusē reāllaikā redzams A un B puses aizpildījums (C-46, C-60, C-90, C-120), brīdinot, ja puse pārsniegta.
5. **Vienas pogas kasetes/lentas kopēšana:** Poga `Kopēt visu kaseti / lentu uz miksteipu` ar vienu klikšķi automātiski iekopē visas A puses dziesmas miksteipa A pusē un B puses dziesmas B pusē, kā arī piešķir miksteipam nosaukumu un pielāgo kasetes garumu (C-60, C-90 utt.). Katrai pusei pieejama arī poga `+ Visa Puse A` un `+ Visa Puse B`.
6. **Draugu Pasūtījumi & Meistara Ieraksta Plāns (Dubbing Sheet):** Drauga pasūtītais miksteips uzreiz parādās Meistara pasūtījumu sarakstā ar soli-pa-solim instrukciju ierakstam pie kasešu dekas (kuru kaseti ņemt, kuru celiņu atskaņot).
7. **Drukājamais J-Card vāciņš:** Standarta 101 mm kasetes vāciņš ar muguriņu un dziesmu sarakstu, ko uzreiz var izdrukāt uz A4 papīra un ielikt kārbiņā.
8. **Vāciņa Foto Pielāgošana & Puscaurspīdīgais Fons:**
   - **Vāciņa foto maiņa formā:** Ja skanēšanai tika nofotografēta ieliktņa iekšpuse (dziesmu saraksts), ar vienu pogu `📷 Nomainīt uz vāciņa foto` var nofotografēt vai augšupielādēt kasetes priekšējo vāciņu.
   - **Puscaurspīdīgais kasetes fons katalogā:** Kasetes kartītē zem dziesmu saraksta cauri spīd kasetes oriģinālais vāciņš, radot reālistisku analogās kasetes korpusa izskatu.
   - **Esošo kasešu vāciņa maiņa:** Katalogā Meistars ar podziņu `📷` var nomainīt vāciņu jebkurai jau saglabātai kasetei, kā arī uzklikšķinot uz mazās bildītes atvērt to pilnā izmērā.
