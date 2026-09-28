# Draft tracker (Sheet1) transcribed 2026-09-28. Number = overall pick (rounds 1-12); None = rounds 13-16 (unnumbered on the sheet).
OWNERS=["Washington","Winters","Cobey","Lerner","Palma","Tchir","Mudge","Williams","Levinsons"]
ROWS={
"C":  ["Rutschman 55","Baldwin 74","Goodman 52","I Herrera 94","S Perez 104","Langeliers 49","W Smith 84","Wm Contreras 29","Raleigh 9"],
"1B": ["Murakami 36","Kurtz 20","Freeman 57","Yandy Diaz 105","Josh Naylor 86","Alonso 31","Devers 48","Guerrero 8","Harper 63"],
"2B": ["Albies 108","Chisholm 35","Altuve 75","Hoerner 40","K Marte 14","Keaschall 60","Turang 30","Lowe 101","Arraez 46"],
"3B": ["Okamoto 90","Bregman 53","M Garcia 34","Riley 58","J Ramirez 5","Caminero 13","E Suarez 97","Machado 26","Bichette 27"],
"SS": ["G Henderson 19","Seager 107","Witt 3","T Turner 22","Betts 32","De La Cruz 6","Perdomo 25","Pena 83","Lindor 10"],
"OF1":["Judge 1","Ohtani 2","Carroll 21","Soto 4","Rooker 23","Bellinger 42","Schwarber 12","Tatis 11","Crow-Armstrong 28"],
"OF2":["Acuna 18","J Rodriguez 17","Anthony 39","Tucker 15","Ja Duran 41","DeLauter 78","Springer 43","Langford 47","Merrill 45"],
"OF3":["Trout 73","Buxton 71","Arozarena 106","Y Alvarez 33","Yelich 59","Suzuki 103","Wood 61","Greene 62","Hernandez 81"],
"RP": ["Chapman 91","Munoz 89","Bednar 93","M Miller 76","Jh Duran 77","C Smith 85","Diaz 66","Helsley 98","D Williams 100"],
"SP1":["Webb 37","Sale 38","Skenes 16","Gilbert 51","Valdez 50","Yamamoto 24","Skubal 7","Alcantara 44","Wheeler 64"],
"SP2":["Fried","H. Brown","C Sanchez","Kirby","Rasmussen","Woo","Crochet","T Rogers","Ragans"],
"SP3":["Cease 54","Ryan 56","Glasnow 70","Luzardo 69","Peralta 68","Pivetta 67","McLean 79","Soriano 65","Chase Burns 82"],
"SP4":["Degrom","Gausman","Misiorowski","Ra Suarez","Horton","Bradish","Schlittler","Abbott","Eovaldi"],
"SP5":["Gray 72","Boyd 92","King 88","Ohtani 87","Imai 95","Gore 96","Bello 102","Woodruff 80","Sheehan 99"],
"SP6":["Castillo","G Williams","Perez","Bubic","Pepiot","Bibee","Bryce Miller","Keller","Detmers"],
"DH": ["Grisham","M Olson","Pasquantino","Soderstrom","Neto","Kwan","Busch","Robert Jr.","Stanton"],
}
# abbrev -> projections_cache full name (manual where surname alone is ambiguous)
ALIAS={
"I Herrera":"Iván Herrera","S Perez":"Salvador Perez","W Smith":"Will Smith","Wm Contreras":"William Contreras",
"Yandy Diaz":"Yandy Díaz","Josh Naylor":"Josh Naylor","Guerrero":"Vladimir Guerrero Jr.","K Marte":"Ketel Marte",
"Lowe":"Brandon Lowe","M Garcia":"Maikel Garcia","J Ramirez":"José Ramírez","E Suarez":"Eugenio Suárez","G Henderson":"Gunnar Henderson",
"T Turner":"Trea Turner","Betts":"Mookie Betts","De La Cruz":"Elly De La Cruz","Perdomo":"Geraldo Perdomo","Pena":"Jeremy Peña",
"Acuna":"Ronald Acuña Jr.","J Rodriguez":"Julio Rodríguez","Anthony":"Roman Anthony","Ja Duran":"Jarren Duran","Ohtani":"Shohei Ohtani",
"Y Alvarez":"Yordan Alvarez","Wood":"James Wood","Greene":"Riley Greene","Hernandez":"Teoscar Hernández","Tatis":"Fernando Tatis Jr.",
"Chapman":"Aroldis Chapman","Munoz":"Andrés Muñoz","Bednar":"David Bednar","M Miller":"Mason Miller","Jh Duran":"Jhoan Duran","C Smith":"Cade Smith",
"Diaz":"Edwin Díaz","Helsley":"Ryan Helsley","D Williams":"Devin Williams",
"H. Brown":"Hunter Brown","C Sanchez":"Cristopher Sánchez","T Rogers":"Trevor Rogers","Ryan":"Joe Ryan","Glasnow":"Tyler Glasnow",
"Degrom":"Jacob deGrom","Ra Suarez":"Ranger Suarez","Gray":"Sonny Gray","King":"Michael King","Ohtani_SP":"Shohei Ohtani",
"Bello":"Brayan Bello","G Williams":"Gavin Williams","Perez":"Eury Pérez","Bryce Miller":"Bryce Miller","Keller":"Mitch Keller",
"M Olson":"Matt Olson","Robert Jr.":"Luis Robert Jr.","Stanton":"Giancarlo Stanton","Neto":"Zach Neto","Kwan":"Steven Kwan","Busch":"Michael Busch",
"Grisham":"Trent Grisham","Soderstrom":"Tyler Soderstrom","Pasquantino":"Vinnie Pasquantino","Chase Burns":"Chase Burns","Crow-Armstrong":"Pete Crow-Armstrong",
"Raleigh":"Cal Raleigh","Lindor":"Francisco Lindor","Skubal":"Tarik Skubal","Skenes":"Paul Skenes","Judge":"Aaron Judge","Soto":"Juan Soto",
"Witt":"Bobby Witt Jr.","Devers":"Rafael Devers","Freeman":"Freddie Freeman","Alonso":"Pete Alonso","Kurtz":"Nick Kurtz","Murakami":"Munetaka Murakami",
"Turang":"Brice Turang","Hoerner":"Nico Hoerner","Altuve":"Jose Altuve","Chisholm":"Jazz Chisholm Jr.","Albies":"Ozzie Albies","Keaschall":"Luke Keaschall",
"Okamoto":"Kazuma Okamoto","Bregman":"Alex Bregman","Riley":"Austin Riley","Caminero":"Junior Caminero","Machado":"Manny Machado","Bichette":"Bo Bichette",
"Seager":"Corey Seager","Carroll":"Corbin Carroll","Rooker":"Brent Rooker","Bellinger":"Cody Bellinger","Schwarber":"Kyle Schwarber","Tucker":"Kyle Tucker",
"DeLauter":"Chase DeLauter","Springer":"George Springer","Langford":"Wyatt Langford","Merrill":"Jackson Merrill","Trout":"Mike Trout","Buxton":"Byron Buxton",
"Arozarena":"Randy Arozarena","Yelich":"Christian Yelich","Suzuki":"Seiya Suzuki","Webb":"Logan Webb","Sale":"Chris Sale","Gilbert":"Logan Gilbert",
"Valdez":"Framber Valdez","Yamamoto":"Yoshinobu Yamamoto","Alcantara":"Sandy Alcantara","Wheeler":"Zack Wheeler","Fried":"Max Fried","Kirby":"George Kirby",
"Rasmussen":"Drew Rasmussen","Woo":"Bryan Woo","Crochet":"Garrett Crochet","Ragans":"Cole Ragans","Cease":"Dylan Cease","Luzardo":"Jesús Luzardo",
"Peralta":"Freddy Peralta","Pivetta":"Nick Pivetta","McLean":"Nolan McLean","Soriano":"José Soriano","Gausman":"Kevin Gausman","Misiorowski":"Jacob Misiorowski",
"Horton":"Cade Horton","Bradish":"Kyle Bradish","Schlittler":"Cam Schlittler","Abbott":"Andrew Abbott","Eovaldi":"Nathan Eovaldi","Boyd":"Matthew Boyd",
"Imai":"Tatsuya Imai","Gore":"MacKenzie Gore","Woodruff":"Brandon Woodruff","Sheehan":"Emmet Sheehan","Castillo":"Luis Castillo","Bubic":"Kris Bubic",
"Pepiot":"Ryan Pepiot","Bibee":"Tanner Bibee","Detmers":"Reid Detmers","Rutschman":"Adley Rutschman","Baldwin":"Drake Baldwin","Goodman":"Hunter Goodman",
"Langeliers":"Shea Langeliers","Harper":"Bryce Harper","Arraez":"Luis Arraez",
}
import re
# Starting pitchers are drafted in PAIRS: the SP2/SP4/SP6 rows share the pick number of SP1/SP3/SP5.
# The DH row is a separate final round (13) taken in the sheet's "DH order".
DH_ORDER={"Washington":4,"Winters":1,"Cobey":2,"Lerner":3,"Palma":6,"Tchir":7,"Mudge":5,"Williams":8,"Levinsons":9}
PAIR={"SP2":"SP1","SP4":"SP3","SP6":"SP5"}
def parse():
    picks=[]  # dict(owner,pos,abbrev,full,pick,pair)
    first={}
    for pos,cells in ROWS.items():
        for owner,cell in zip(OWNERS,cells):
            m=re.match(r"^(.*?)\s*(\d+)?$",cell.strip()); ab=m.group(1).strip(); pk=int(m.group(2)) if m.group(2) else None
            if pk: first[(owner,pos)]=pk
            key="Ohtani_SP" if (ab=="Ohtani" and pos.startswith("SP")) else ab
            picks.append(dict(owner=owner,pos=pos,abbrev=ab,full=ALIAS.get(key),pick=pk,pair=False,ptype=("sp" if pos.startswith("SP") else "rp" if pos=="RP" else "hitter")))
    for p in picks:
        if p["pos"] in PAIR: p["pick"]=first[(p["owner"],PAIR[p["pos"]])]; p["pair"]=True
        if p["pos"]=="DH": p["pick"]=108+DH_ORDER[p["owner"]]
    return picks
def round_of(pk): return 13 if pk>108 else (pk-1)//9+1
