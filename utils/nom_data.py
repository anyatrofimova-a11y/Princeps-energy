"""
Network Opportunity Map (NOM) — synthetic dataset generator & query helpers.

Generates ~600 substations (BSP + Primary) across UK DNO licence areas
with realistic headroom values, RAG ratings, and geographic placement.
"""

import math
import random
import hashlib
from typing import Optional

# ---------------------------------------------------------------------------
# UK DNO Licence areas with representative towns/cities
# ---------------------------------------------------------------------------
LICENCE_AREAS = {
    "East Midlands": {
        "dno": "NGED",
        "gsps": ["East Midlands GSP"],
        "towns": [
            ("Nottingham", 52.9548, -1.1581),
            ("Leicester", 52.6369, -1.1398),
            ("Derby", 52.9225, -1.4746),
            ("Lincoln", 53.2307, -0.5406),
            ("Northampton", 52.2405, -0.9027),
            ("Mansfield", 53.1397, -1.1972),
            ("Loughborough", 52.7721, -1.2062),
            ("Corby", 52.4886, -0.6913),
            ("Kettering", 52.3931, -0.7230),
            ("Wellingborough", 52.3027, -0.6946),
            ("Grantham", 52.9118, -0.6383),
            ("Newark", 53.0768, -0.8092),
            ("Chesterfield", 53.2353, -1.4217),
            ("Boston", 52.9772, -0.0263),
            ("Skegness", 53.1461, 0.3367),
            ("Melton Mowbray", 52.7652, -0.8867),
            ("Hinckley", 52.5410, -1.3726),
            ("Coalville", 52.7266, -1.3699),
            ("Ilkeston", 52.9714, -1.3092),
            ("Buxton", 53.2583, -1.9115),
        ],
    },
    "West Midlands": {
        "dno": "NGED",
        "gsps": ["West Midlands GSP"],
        "towns": [
            ("Birmingham", 52.4862, -1.8904),
            ("Coventry", 52.4068, -1.5197),
            ("Wolverhampton", 52.5870, -2.1288),
            ("Stoke-on-Trent", 53.0027, -2.1794),
            ("Walsall", 52.5860, -1.9827),
            ("Dudley", 52.5087, -2.0818),
            ("Solihull", 52.4128, -1.7743),
            ("Telford", 52.6779, -2.4453),
            ("Worcester", 52.1920, -2.2214),
            ("Shrewsbury", 52.7077, -2.7537),
            ("Hereford", 52.0565, -2.7160),
            ("Stafford", 52.8071, -2.1171),
            ("Tamworth", 52.6341, -1.6909),
            ("Kidderminster", 52.3884, -2.2500),
            ("Redditch", 52.3065, -1.9454),
            ("Lichfield", 52.6836, -1.8262),
            ("Cannock", 52.6909, -1.9805),
            ("Nuneaton", 52.5237, -1.4679),
            ("Rugby", 52.3709, -1.2616),
            ("Leamington Spa", 52.2919, -1.5364),
        ],
    },
    "South West": {
        "dno": "NGED",
        "gsps": ["South West GSP"],
        "towns": [
            ("Bristol", 51.4545, -2.5879),
            ("Plymouth", 50.3755, -4.1427),
            ("Exeter", 50.7184, -3.5339),
            ("Bath", 51.3758, -2.3599),
            ("Gloucester", 51.8642, -2.2382),
            ("Cheltenham", 51.8994, -2.0783),
            ("Taunton", 51.0151, -3.1005),
            ("Swindon", 51.5558, -1.7797),
            ("Bournemouth", 50.7192, -1.8808),
            ("Poole", 50.7151, -1.9871),
            ("Salisbury", 51.0688, -1.7945),
            ("Torquay", 50.4619, -3.5253),
            ("Barnstaple", 51.0800, -4.0581),
            ("Truro", 50.2632, -5.0510),
            ("Penzance", 50.1186, -5.5324),
            ("Weston-super-Mare", 51.3462, -2.9760),
            ("Yeovil", 50.9453, -2.6326),
            ("Bridgwater", 51.1280, -3.0036),
            ("Dorchester", 50.7154, -2.4379),
            ("Chippenham", 51.4596, -2.1155),
        ],
    },
    "South Wales": {
        "dno": "NGED",
        "gsps": ["South Wales GSP"],
        "towns": [
            ("Cardiff", 51.4816, -3.1791),
            ("Swansea", 51.6214, -3.9436),
            ("Newport", 51.5842, -2.9977),
            ("Merthyr Tydfil", 51.7491, -3.3757),
            ("Bridgend", 51.5079, -3.5766),
            ("Neath", 51.6604, -3.8033),
            ("Port Talbot", 51.5912, -3.7746),
            ("Pontypridd", 51.6021, -3.3425),
            ("Llanelli", 51.6839, -4.1629),
            ("Carmarthen", 51.8561, -4.3120),
            ("Barry", 51.4000, -3.2700),
            ("Cwmbran", 51.6537, -3.0216),
            ("Caerphilly", 51.5783, -3.2183),
            ("Aberdare", 51.7147, -3.4432),
            ("Ebbw Vale", 51.7785, -3.2087),
        ],
    },
    "South East": {
        "dno": "UKPN",
        "gsps": ["South East GSP"],
        "towns": [
            ("Brighton", 50.8225, -0.1372),
            ("Southampton", 50.9097, -1.4044),
            ("Portsmouth", 50.8198, -1.0880),
            ("Reading", 51.4543, -0.9781),
            ("Oxford", 51.7520, -1.2577),
            ("Guildford", 51.2362, -0.5704),
            ("Canterbury", 51.2802, 1.0789),
            ("Maidstone", 51.2720, 0.5292),
            ("Crawley", 51.1092, -0.1872),
            ("Basingstoke", 51.2667, -1.0877),
            ("Milton Keynes", 52.0406, -0.7594),
            ("Slough", 51.5105, -0.5950),
            ("Tunbridge Wells", 51.1322, 0.2635),
            ("Folkestone", 51.0817, 1.1690),
            ("Hastings", 50.8531, 0.5732),
            ("Ashford", 51.1498, 0.8720),
            ("Aylesbury", 51.8168, -0.8084),
            ("Margate", 51.3813, 1.3863),
            ("Dover", 51.1279, 1.3134),
            ("Chatham", 51.3700, 0.5217),
        ],
    },
    "Eastern": {
        "dno": "UKPN",
        "gsps": ["Eastern GSP"],
        "towns": [
            ("Norwich", 52.6309, 1.2974),
            ("Cambridge", 52.2053, 0.1218),
            ("Ipswich", 52.0567, 1.1482),
            ("Luton", 51.8787, -0.4200),
            ("Colchester", 51.8891, 0.9029),
            ("Chelmsford", 51.7356, 0.4685),
            ("Peterborough", 52.5695, -0.2405),
            ("Stevenage", 51.9017, -0.2030),
            ("Bedford", 52.1356, -0.4669),
            ("Kings Lynn", 52.7537, 0.3966),
            ("Great Yarmouth", 52.6062, 1.7307),
            ("Lowestoft", 52.4760, 1.7540),
            ("Bury St Edmunds", 52.2472, 0.7177),
            ("Harlow", 51.7727, 0.1004),
            ("Basildon", 51.5761, 0.4887),
            ("Southend-on-Sea", 51.5405, 0.7107),
            ("Braintree", 51.8787, 0.5533),
            ("Thetford", 52.4136, 0.7438),
            ("Newmarket", 52.2448, 0.4059),
            ("Huntingdon", 52.3309, -0.1851),
        ],
    },
    "North West": {
        "dno": "ENWL",
        "gsps": ["North West GSP"],
        "towns": [
            ("Manchester", 53.4808, -2.2426),
            ("Liverpool", 53.4084, -2.9916),
            ("Preston", 53.7632, -2.7031),
            ("Blackpool", 53.8175, -3.0357),
            ("Bolton", 53.5778, -2.4282),
            ("Warrington", 53.3900, -2.5970),
            ("Wigan", 53.5450, -2.6325),
            ("Stockport", 53.4106, -2.1575),
            ("Blackburn", 53.7488, -2.4818),
            ("Burnley", 53.7893, -2.2413),
            ("Chester", 53.1906, -2.8909),
            ("Crewe", 53.0989, -2.4400),
            ("Macclesfield", 53.2585, -2.1248),
            ("Lancaster", 54.0466, -2.8007),
            ("Carlisle", 54.8951, -2.9382),
            ("Barrow-in-Furness", 54.1110, -3.2266),
            ("Kendal", 54.3281, -2.7458),
            ("Workington", 54.6425, -3.5439),
            ("Penrith", 54.6648, -2.7559),
            ("Rochdale", 53.6157, -2.1561),
        ],
    },
    "Yorkshire": {
        "dno": "NPG",
        "gsps": ["Yorkshire GSP"],
        "towns": [
            ("Leeds", 53.8008, -1.5491),
            ("Sheffield", 53.3811, -1.4701),
            ("Bradford", 53.7960, -1.7594),
            ("York", 53.9591, -1.0815),
            ("Hull", 53.7676, -0.3274),
            ("Huddersfield", 53.6458, -1.7850),
            ("Doncaster", 53.5228, -1.1288),
            ("Wakefield", 53.6833, -1.4977),
            ("Harrogate", 53.9921, -1.5418),
            ("Scarborough", 54.2791, -0.4050),
            ("Barnsley", 53.5526, -1.4793),
            ("Rotherham", 53.4326, -1.3635),
            ("Halifax", 53.7227, -1.8627),
            ("Grimsby", 53.5676, -0.0803),
            ("Scunthorpe", 53.5809, -0.6538),
            ("Selby", 53.7835, -1.0681),
            ("Skipton", 53.9614, -2.0174),
            ("Thirsk", 54.2321, -1.3435),
            ("Beverley", 53.8425, -0.4276),
            ("Bridlington", 54.0832, -0.1910),
        ],
    },
    "North East": {
        "dno": "NPG",
        "gsps": ["North East GSP"],
        "towns": [
            ("Newcastle", 54.9783, -1.6178),
            ("Sunderland", 54.9069, -1.3838),
            ("Durham", 54.7753, -1.5849),
            ("Darlington", 54.5235, -1.5527),
            ("Middlesbrough", 54.5742, -1.2350),
            ("Hartlepool", 54.6863, -1.2130),
            ("Gateshead", 54.9594, -1.6031),
            ("South Shields", 54.9988, -1.4320),
            ("Washington", 54.9000, -1.5180),
            ("Blyth", 55.1265, -1.5084),
            ("Hexham", 54.9708, -2.1006),
            ("Alnwick", 55.4131, -1.7064),
            ("Berwick-upon-Tweed", 55.7710, -2.0000),
            ("Bishop Auckland", 54.6624, -1.6767),
            ("Consett", 54.8531, -1.8316),
        ],
    },
    "Southern Scotland": {
        "dno": "SSEN",
        "gsps": ["Southern Scotland GSP"],
        "towns": [
            ("Edinburgh", 55.9533, -3.1883),
            ("Glasgow", 55.8642, -4.2518),
            ("Dundee", 56.4620, -2.9707),
            ("Aberdeen", 57.1497, -2.0943),
            ("Stirling", 56.1165, -3.9369),
            ("Perth", 56.3953, -3.4372),
            ("Inverness", 57.4778, -4.2247),
            ("Ayr", 55.4584, -4.6300),
            ("Dumfries", 55.0700, -3.6050),
            ("Paisley", 55.8464, -4.4236),
            ("East Kilbride", 55.7643, -4.1768),
            ("Livingston", 55.8839, -3.5157),
            ("Falkirk", 56.0019, -3.7893),
            ("Dunfermline", 56.0719, -3.4393),
            ("Kirkcaldy", 56.1132, -3.1595),
        ],
    },
}

# Local authority assignments (simplified — map town to LA)
TOWN_TO_LA = {
    "Nottingham": "Nottingham City",
    "Leicester": "Leicester City",
    "Derby": "Derby City",
    "Lincoln": "City of Lincoln",
    "Northampton": "West Northamptonshire",
    "Birmingham": "Birmingham City",
    "Coventry": "Coventry City",
    "Wolverhampton": "City of Wolverhampton",
    "Bristol": "City of Bristol",
    "Plymouth": "Plymouth City",
    "Exeter": "Exeter City",
    "Cardiff": "Cardiff Council",
    "Swansea": "City and County of Swansea",
    "Newport": "Newport City",
    "Brighton": "Brighton and Hove",
    "Southampton": "Southampton City",
    "Portsmouth": "Portsmouth City",
    "Reading": "Reading Borough",
    "Oxford": "Oxford City",
    "Norwich": "Norwich City",
    "Cambridge": "Cambridge City",
    "Ipswich": "Ipswich Borough",
    "Manchester": "Manchester City",
    "Liverpool": "Liverpool City",
    "Preston": "Preston City",
    "Leeds": "Leeds City",
    "Sheffield": "Sheffield City",
    "Bradford": "City of Bradford",
    "Newcastle": "Newcastle City",
    "Sunderland": "Sunderland City",
    "Edinburgh": "City of Edinburgh",
    "Glasgow": "Glasgow City",
    "Dundee": "Dundee City",
    "Aberdeen": "Aberdeen City",
}

# Supply types and demand constraints
SUPPLY_TYPES = ["Demand", "Generation", "Mixed"]
DEMAND_CONSTRAINTS = ["Thermal", "Voltage", "Fault Level"]


def _seed_for(name: str) -> int:
    """Deterministic seed from substation name for reproducible data."""
    return int(hashlib.md5(name.encode()).hexdigest()[:8], 16)


def _rag(headroom: float, threshold_green: float, threshold_amber: float) -> str:
    """Assign RAG rating based on headroom thresholds."""
    if headroom >= threshold_green:
        return "Green"
    if headroom >= threshold_amber:
        return "Amber"
    return "Red"


def _lat_lon_to_bng(lat: float, lon: float) -> tuple[int, int]:
    """Approximate WGS84 to BNG (OSGB36) conversion for UK coordinates."""
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    a = 6377563.396
    b = 6356256.909
    F0 = 0.9996012717
    lat0 = math.radians(49)
    lon0 = math.radians(-2)
    N0 = -100000
    E0 = 400000
    e2 = 1 - (b * b) / (a * a)
    n = (a - b) / (a + b)

    nu = a * F0 * (1 - e2 * math.sin(lat_r) ** 2) ** -0.5
    rho = a * F0 * (1 - e2) * (1 - e2 * math.sin(lat_r) ** 2) ** -1.5
    eta2 = nu / rho - 1

    Ma = (1 + n + (5 / 4) * n ** 2 + (5 / 4) * n ** 3) * (lat_r - lat0)
    Mb = (3 * n + 3 * n ** 2 + (21 / 8) * n ** 3) * math.sin(lat_r - lat0) * math.cos(lat_r + lat0)
    Mc = ((15 / 8) * n ** 2 + (15 / 8) * n ** 3) * math.sin(2 * (lat_r - lat0)) * math.cos(2 * (lat_r + lat0))
    Md = (35 / 24) * n ** 3 * math.sin(3 * (lat_r - lat0)) * math.cos(3 * (lat_r + lat0))
    M = b * F0 * (Ma - Mb + Mc - Md)

    cos_lat = math.cos(lat_r)
    sin_lat = math.sin(lat_r)
    tan_lat = math.tan(lat_r)
    dl = lon_r - lon0

    I = M + N0
    II = (nu / 2) * sin_lat * cos_lat
    III = (nu / 24) * sin_lat * cos_lat ** 3 * (5 - tan_lat ** 2 + 9 * eta2)
    IIIA = (nu / 720) * sin_lat * cos_lat ** 5 * (61 - 58 * tan_lat ** 2 + tan_lat ** 4)
    IV = nu * cos_lat
    V = (nu / 6) * cos_lat ** 3 * (nu / rho - tan_lat ** 2)
    VI = (nu / 120) * cos_lat ** 5 * (5 - 18 * tan_lat ** 2 + tan_lat ** 4 + 14 * eta2 - 58 * tan_lat ** 2 * eta2)

    northing = int(I + II * dl ** 2 + III * dl ** 4 + IIIA * dl ** 6)
    easting = int(E0 + IV * dl + V * dl ** 3 + VI * dl ** 5)
    return easting, northing


def _generate_substations() -> list[dict]:
    """Generate ~600 synthetic substations across all licence areas."""
    substations = []
    sub_number = 1000

    for area_name, area_info in LICENCE_AREAS.items():
        towns = area_info["towns"]
        gsp_name = area_info["gsps"][0]
        dno = area_info["dno"]

        # BSPs: 1 per ~2-3 major towns (typically 4-8 per licence area)
        n_bsp = max(3, len(towns) // 3)
        bsp_towns = towns[:n_bsp]

        for i, (town, lat, lon) in enumerate(bsp_towns):
            rng = random.Random(_seed_for(f"BSP-{area_name}-{town}"))
            sub_number += 1

            # BSP headroom: 0-50 MW range
            dem_conn_hw = round(rng.uniform(-5, 50), 1)
            dem_cont_hw = round(dem_conn_hw + rng.uniform(-10, 5), 1)
            gen_conn_hw = round(rng.uniform(-5, 50), 1)
            gen_cont_hw = round(gen_conn_hw + rng.uniform(-15, 5), 1)

            # Clamp negatives to small negative values
            dem_conn_hw = max(-5, dem_conn_hw)
            dem_cont_hw = max(-5, dem_cont_hw)
            gen_conn_hw = max(-5, gen_conn_hw)
            gen_cont_hw = max(-5, gen_cont_hw)

            easting, northing = _lat_lon_to_bng(lat, lon)
            la = TOWN_TO_LA.get(town, f"{town} District")

            substations.append({
                "substation_name": f"{town} BSP",
                "substation_number": f"BSP{sub_number}",
                "substation_type": "BSP",
                "demand_connected_headroom_mw": dem_conn_hw,
                "demand_connected_rag": _rag(dem_conn_hw, 25, 10),
                "demand_contracted_headroom_mw": dem_cont_hw,
                "demand_contracted_rag": _rag(dem_cont_hw, 25, 10),
                "generation_connected_headroom_mw": gen_conn_hw,
                "generation_connected_rag": _rag(gen_conn_hw, 25, 10),
                "generation_contracted_headroom_mw": gen_cont_hw,
                "generation_contracted_rag": _rag(gen_cont_hw, 25, 10),
                "gsp": gsp_name,
                "licence_area": area_name,
                "dno": dno,
                "local_authority": la,
                "supply_type": rng.choice(SUPPLY_TYPES),
                "demand_constraint": rng.choice(DEMAND_CONSTRAINTS),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "easting": easting,
                "northing": northing,
                "description": f"132/33kV Bulk Supply Point serving {town} and surrounding area. "
                               f"Connected to {gsp_name}.",
            })

        # Primaries: rest of towns + additional synthetic substations
        for j, (town, lat, lon) in enumerate(towns):
            rng = random.Random(_seed_for(f"PRI-{area_name}-{town}"))

            # Generate 2-4 primaries per town (spread around town centre)
            n_pri = rng.randint(2, 4)
            for k in range(n_pri):
                sub_number += 1
                # Offset from town centre (±0.02° ≈ 1-2 km)
                plat = lat + rng.uniform(-0.02, 0.02)
                plon = lon + rng.uniform(-0.03, 0.03)

                # Primary headroom: 0-15 MW range
                dem_conn_hw = round(rng.uniform(-2, 15), 1)
                dem_cont_hw = round(dem_conn_hw + rng.uniform(-5, 3), 1)
                gen_conn_hw = round(rng.uniform(-2, 15), 1)
                gen_cont_hw = round(gen_conn_hw + rng.uniform(-8, 3), 1)

                dem_conn_hw = max(-2, dem_conn_hw)
                dem_cont_hw = max(-2, dem_cont_hw)
                gen_conn_hw = max(-2, gen_conn_hw)
                gen_cont_hw = max(-2, gen_cont_hw)

                easting, northing = _lat_lon_to_bng(plat, plon)
                la = TOWN_TO_LA.get(town, f"{town} District")

                # Name variants for primaries
                suffixes = ["North", "South", "East", "West", "Central", "Park",
                            "Road", "Lane", "Hill", "Green", "Industrial"]
                suffix = rng.choice(suffixes)
                parent_bsp = f"{bsp_towns[j % len(bsp_towns)][0]} BSP"

                substations.append({
                    "substation_name": f"{town} {suffix} Primary",
                    "substation_number": f"PRI{sub_number}",
                    "substation_type": "Primary",
                    "demand_connected_headroom_mw": dem_conn_hw,
                    "demand_connected_rag": _rag(dem_conn_hw, 8, 4),
                    "demand_contracted_headroom_mw": dem_cont_hw,
                    "demand_contracted_rag": _rag(dem_cont_hw, 8, 4),
                    "generation_connected_headroom_mw": gen_conn_hw,
                    "generation_connected_rag": _rag(gen_conn_hw, 8, 4),
                    "generation_contracted_headroom_mw": gen_cont_hw,
                    "generation_contracted_rag": _rag(gen_cont_hw, 8, 4),
                    "gsp": gsp_name,
                    "licence_area": area_name,
                    "dno": dno,
                    "local_authority": la,
                    "supply_type": rng.choice(SUPPLY_TYPES),
                    "demand_constraint": rng.choice(DEMAND_CONSTRAINTS),
                    "lat": round(plat, 6),
                    "lon": round(plon, 6),
                    "easting": easting,
                    "northing": northing,
                    "description": f"33/11kV Primary substation in {town}. Fed from {parent_bsp}.",
                })

    return substations


# ---------------------------------------------------------------------------
# Singleton dataset — generated once on import
# ---------------------------------------------------------------------------
_SUBSTATIONS: list[dict] = []


def _get_substations() -> list[dict]:
    global _SUBSTATIONS
    if not _SUBSTATIONS:
        _SUBSTATIONS = _generate_substations()
    return _SUBSTATIONS


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_all_substations(
    type_filter: Optional[str] = None,
    rag_filter: Optional[str] = None,
    licence_area: Optional[str] = None,
    local_authority: Optional[str] = None,
    supply_type: Optional[str] = None,
    constraint: Optional[str] = None,
    search: Optional[str] = None,
    view: str = "connected",
    map_type: Optional[str] = None,
) -> list[dict]:
    """Filter substations by multiple criteria.

    map_type can be: 'primary_demand', 'primary_generation', 'bsp_demand', 'bsp_generation'
    view: 'connected' or 'contracted'
    rag_filter applies to the relevant headroom field based on map_type + view
    """
    subs = _get_substations()
    result = []

    # Determine which headroom/RAG field to use for filtering
    if map_type:
        parts = map_type.lower().split("_")
        sub_type = parts[0] if parts else None  # primary or bsp
        direction = parts[1] if len(parts) > 1 else None  # demand or generation
    else:
        sub_type = None
        direction = None

    for s in subs:
        # Type filter (from map_type or explicit)
        if type_filter and s["substation_type"].lower() != type_filter.lower():
            continue
        if sub_type:
            if sub_type == "primary" and s["substation_type"] != "Primary":
                continue
            if sub_type == "bsp" and s["substation_type"] != "BSP":
                continue

        # RAG filter — apply to the field determined by map_type + view
        if rag_filter:
            if direction and view:
                rag_key = f"{direction}_{view}_rag"
                rag_val = s.get(rag_key, "")
            else:
                # Default: check generation connected RAG
                rag_val = s.get("generation_connected_rag", "")
            if rag_val.lower() != rag_filter.lower():
                continue

        if licence_area and licence_area != "Show all":
            if s["licence_area"].lower() != licence_area.lower():
                continue
        if local_authority and local_authority != "Show all":
            if s["local_authority"].lower() != local_authority.lower():
                continue
        if supply_type and supply_type != "Show all":
            if s["supply_type"].lower() != supply_type.lower():
                continue
        if constraint and constraint != "Show all":
            if s["demand_constraint"].lower() != constraint.lower():
                continue
        if search:
            q = search.lower()
            if (q not in s["substation_name"].lower() and
                q not in s["substation_number"].lower() and
                q not in s["local_authority"].lower()):
                continue

        result.append(s)

    return result


def get_substation_by_id(sub_number: str) -> Optional[dict]:
    """Find a single substation by its number."""
    for s in _get_substations():
        if s["substation_number"] == sub_number:
            return s
    return None


def get_nom_geojson(
    type_filter: Optional[str] = None,
    rag_filter: Optional[str] = None,
    licence_area: Optional[str] = None,
    local_authority: Optional[str] = None,
    supply_type: Optional[str] = None,
    constraint: Optional[str] = None,
    search: Optional[str] = None,
    view: str = "connected",
    map_type: Optional[str] = None,
) -> dict:
    """Return filtered substations as a GeoJSON FeatureCollection."""
    subs = get_all_substations(
        type_filter=type_filter, rag_filter=rag_filter,
        licence_area=licence_area, local_authority=local_authority,
        supply_type=supply_type, constraint=constraint,
        search=search, view=view, map_type=map_type,
    )

    # Determine which headroom/RAG to use for styling
    if map_type:
        parts = map_type.lower().split("_")
        direction = parts[1] if len(parts) > 1 else "generation"
    else:
        direction = "generation"
    hw_key = f"{direction}_{view}_headroom_mw"
    rag_key = f"{direction}_{view}_rag"

    features = []
    for s in subs:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [s["lon"], s["lat"]],
            },
            "properties": {
                **s,
                "display_headroom_mw": s.get(hw_key, 0),
                "display_rag": s.get(rag_key, "Amber"),
            },
        })

    return {"type": "FeatureCollection", "features": features}


def get_nom_summary() -> dict:
    """Aggregate stats: total substations, RAG distribution, headroom totals."""
    subs = _get_substations()

    bsp_count = sum(1 for s in subs if s["substation_type"] == "BSP")
    pri_count = sum(1 for s in subs if s["substation_type"] == "Primary")

    # Generation connected RAG distribution (most common view)
    rag_dist = {"Green": 0, "Amber": 0, "Red": 0}
    total_gen_hw = 0
    total_dem_hw = 0
    for s in subs:
        rag_dist[s["generation_connected_rag"]] += 1
        total_gen_hw += max(0, s["generation_connected_headroom_mw"])
        total_dem_hw += max(0, s["demand_connected_headroom_mw"])

    # Per-licence-area counts
    area_counts = {}
    for s in subs:
        area = s["licence_area"]
        if area not in area_counts:
            area_counts[area] = 0
        area_counts[area] += 1

    return {
        "total": len(subs),
        "bsp_count": bsp_count,
        "primary_count": pri_count,
        "rag_distribution": rag_dist,
        "total_generation_headroom_mw": round(total_gen_hw, 1),
        "total_demand_headroom_mw": round(total_dem_hw, 1),
        "licence_area_counts": area_counts,
    }


def get_licence_areas() -> list[dict]:
    """List available licence areas with counts."""
    subs = _get_substations()
    area_map: dict[str, dict] = {}
    for s in subs:
        area = s["licence_area"]
        if area not in area_map:
            area_map[area] = {"name": area, "dno": s["dno"], "count": 0}
        area_map[area]["count"] += 1
    return sorted(area_map.values(), key=lambda x: x["name"])


def get_local_authorities() -> list[str]:
    """List all unique local authorities in the dataset."""
    subs = _get_substations()
    return sorted({s["local_authority"] for s in subs})
