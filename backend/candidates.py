"""Kandidaten für die Erkennung von Regionen und Hashtag-Räumen.

Regions-Codes und Hashtag-Kanäle lassen sich nicht zurückrechnen, nur gegen bekannte
Namen prüfen. Diese Listen decken die Region SaarLorLux und gängige Namen ab.
Erweitern: einfach Namen ergänzen (klein, ohne '#'); Umlaute als eigene Variante.
"""

REGIONS = """
saarland saar sl saarlorlux saar-lor-lux grossregion großregion
saarbruecken saarbrücken sb saarlouis merzig merzig-wadern wadern neunkirchen homburg saarpfalz
st-ingbert stingbert sanktingbert st-wendel stwendel sanktwendel voelklingen völklingen dillingen
blieskastel losheim lebach ottweiler illingen schmelz wadgassen bexbach kirkel perl mettlach
pfalz westpfalz rlp rheinland-pfalz rheinlandpfalz zweibruecken zweibrücken pirmasens kaiserslautern kl
trier mosel hunsrueck hunsrück eifel idar-oberstein birkenfeld kusel landstuhl
mainz koblenz ludwigshafen worms speyer landau neustadt
lorraine lothringen moselle metz nancy thionville forbach sarreguemines sarrebourg saint-avold creutzwald
alsace elsass strasbourg grand-est grandest
lu lux luxembourg luxemburg letzebuerg eschsuralzette esch
be belgique belgien wallonie arlon
de deu germany deutschland fr france frankreich nl at ch eu europe europa
bw baden-wuerttemberg badenwuerttemberg bayern by hessen he nrw nordrhein-westfalen sachsen sn
niedersachsen nds schleswig-holstein sh hamburg hh bremen hb berlin brandenburg bb
mecklenburg-vorpommern mv sachsen-anhalt st thueringen thüringen th
karlsruhe mannheim heidelberg stuttgart frankfurt wiesbaden darmstadt koeln köln duesseldorf
muenchen münchen nuernberg nürnberg leipzig dresden hannover
de-sl de-rp de-bw de-by de-be de-bb de-hb de-hh de-he de-mv de-ni de-nw de-sn de-st de-sh de-th
de-west de-ost de-nord de-sued de-süd de-mitte de-nordwest de-nordost de-suedwest de-südwest de-suedost de-südost
de-saar de-pfalz scn lux-de fr-ge fr-57 fr-67 fr-68 lu-ca
test local lokal regional home mesh meshcore
"""

ROOMS = """
public test testing tests chat general allgemein offtopic off-topic random talk
notfall emergency help hilfe sos katastrophenschutz
technik tech repeater repeaters mesh meshcore meshtastic lora funk amateurfunk hamradio ham dx
wetter weather news nachrichten info infos ankuendigungen announcements events treffen stammtisch
sensor sensors telemetrie telemetry bot bots ping echo admin admins dev entwicklung firmware
verkehr bahn auto wandern outdoor gaming
"""


def names(block: str) -> list[str]:
    return list(dict.fromkeys(block.split()))


REGION_NAMES = names(REGIONS)
ROOM_NAMES = names(ROOMS + REGIONS)
