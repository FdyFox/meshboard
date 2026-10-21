# Changelog

## Unveröffentlicht

- Regionen: `de-sl`, `de-rp`, `de-west`, `de-mitte`, `de-sued` u. a. erkannt, Regionsnamen von CoreScope (falls eingeschaltet), ältere Pakete und Nachrichten mit „Region ?…“ werden nachträglich zugeordnet
- Gerät › Im Netz gehört: übersichtlicher (zwei breite Spalten, „gehört von“ einzeilig mit Tooltip)
- Chat: Klick auf den Absendernamen öffnet das Detailfenster des Knotens
- Chat: „✉ Privat antworten“ an jeder Kanalnachricht – unbekannte Absender werden per Name gesucht (gehört oder CoreScope) und als Kontakt gespeichert
- Unbekannte Knoten auf CoreScope (z. B. live.saarmesh.de) nachschlagen: Hop-Hashes im Hintergrund, Treffer in der globalen Suche, Quelle in Kontakten, Karte und Detailfenster (Einstellung unter Gerät › App, standardmäßig aus)
- Chat: Repeater-Zähler für eigene Nachrichten. Grauer Haken = gesendet ohne Rückmeldung, grüner Haken mit Zahl = so viele Repeater wurden beim Weiterleiten gehört (Klick zeigt Namen und SNR)
- Chat: Kanalnachrichten, die nach 60 s kein Repeater weitergeleitet hat, lassen sich erneut senden
- Statistik › Knoten: Hash-Kollisionen (aktive Repeater mit gleichem Hop-Hash bei 1, 2 und 3 Byte), Hinweis in der Übersicht
- Knoten beobachten: Meldung, wenn ein Knoten länger als die Schwelle nicht gehört wurde und wenn er wieder da ist
- Repeater verwalten: Anmeldung, Status, Nachbarliste und CLI-Konsole für Repeater und Room-Server
- Trace mit SNR je Abschnitt, Pfadvorschlag aus dem Kontaktpfad
- Auto-Antwort pro Kanal mit Auslösewörtern, eigener Vorlage und Schutz gegen Fluten
- Push-Benachrichtigungen über ntfy, Telegram oder Webhook
- Gehörte Knoten im Gerät speichern (Kontakte und Karten-Popup), Popup mit „Verwalten“ bzw. „Trace“ für gespeicherte Kontakte
- Schnellantwort-Vorlage wird jetzt vom Server gefüllt (auch die Vorschau); Docker-Image mit `TZ=Europe/Berlin`
- Live-Traffic: Rohdaten farbig nach Abschnitten aufgeschlüsselt, Direktlink auf Pakete (`#live/<id>`, auch ältere aus dem Verlauf)
- Karte: Pakete live animieren, Wiedergabe der letzten 1 h bis 3 Tage im Zeitraffer
- Globale Suche (Strg+K oder /) über Knoten, Kontakte, Kanäle, Räume und Nachrichten
- Knoten-Details: Ankunft über welche Nachbarn, Nachbarn im Netz, Aktivität nach Wochentag × Uhrzeit, SNR-Verteilung
- Statistik › Routen: Funkverbindungen auf der Karte, häufigste Pfade, weiteste Verbindungen
- Mehrdeutige Hop-Hashes werden nach Lage zugeordnet (kürzester plausibler Weg, Repeater bevorzugt) – in Live-Traffic, Karte, Statistik und Schnellantwort `{km}`

## 0.1.0

Erste Version von Meshboard.

- Server (FastAPI + meshcore) verbindet sich per TCP, USB oder BLE mit der Node und hält die Verbindung dauerhaft
- Live-Traffic, Chat mit Zustellbestätigung, Karte (OpenFreeMap), Kontakte, Geräteeinstellungen
- Regionen pro Kanal, Erkennung von Regionen und gehörten Hashtag-Räumen
- Schnellantwort mit Vorlage, Benachrichtigung pro Unterhaltung
- Statistik mit Paketverlauf und Gerätewerten (Übersicht, Funk & Gerät, Netz, Knoten, Nachrichten)
- Docker-Image für amd64 und arm64
