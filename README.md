# Fonteyn Monitoring Scripts

Welkom bij de repository voor het monitoring- en autoscalingproject van Fonteyn Vakantieparken.  
Deze repository bevat Python-scripts voor het automatisch aansturen van containers op basis van netwerkactiviteit en het aanmaken van incidenttickets bij overschrijding van CPU- of RAM-drempels.

 **Meer informatie?**
Bekijk de uitgebreide uitleg, architectuur, .env-sjablonen en configuratie-instructies in de **[Wiki](../../wiki)**.

---

Snelstartgids:
- Zorg dat je `.env` correct is ingesteld (zie Wiki)
- Installeer dependencies met `pip install -r requirements.txt`
- Start het gewenste script: `python autoscaler.py` of `python ticketcreator.py`
