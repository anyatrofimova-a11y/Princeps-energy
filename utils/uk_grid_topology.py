"""
UK National Grid topology for flow-map visualisation.

Generates ~330 nodes (GSPs, BSPs, major substations) covering all of Great Britain
and ~500 transmission lines connecting them in a realistic radial/mesh topology.
Node locations are based on real National Grid ESO GSP coordinates and populated areas.
Flow values are distributed from generation zones toward demand centres.
"""

import math
import random

# Seed for reproducibility
random.seed(42)

# ── Real UK Grid Supply Points & Bulk Supply Points ──
# Based on National Grid ESO GSP group data + major substations
# Format: (name, lat, lon, voltage_kv, type, demand_mw)
_GRID_NODES_RAW = [
    # === 400kV Supergrid nodes (major GSPs) ===
    ("Beauly", 57.468, -4.496, 275, "gsp", 180),
    ("Dounreay", 58.580, -3.750, 275, "gsp", 60),
    ("Kintore", 57.230, -2.350, 275, "gsp", 220),
    ("Peterhead", 57.477, -1.789, 400, "gsp", 340),
    ("Longannet", 56.060, -3.710, 400, "gsp", 280),
    ("Cockenzie", 55.970, -2.970, 400, "gsp", 300),
    ("Torness", 55.970, -2.400, 400, "gsp", 590),
    ("Hunterston", 55.720, -4.890, 400, "gsp", 480),
    ("Strathaven", 55.700, -4.060, 400, "gsp", 350),
    ("Windyhill", 55.910, -4.370, 275, "gsp", 410),
    ("Bathgate", 55.890, -3.630, 275, "gsp", 260),
    ("Kaimes", 55.880, -3.240, 275, "gsp", 320),
    ("Smeaton", 55.920, -3.020, 275, "gsp", 210),
    ("Eccles", 55.640, -2.350, 275, "gsp", 180),
    ("Harker", 54.940, -2.920, 400, "gsp", 250),
    ("Stella West", 54.960, -1.710, 275, "gsp", 380),
    ("Blyth", 55.130, -1.510, 275, "gsp", 200),
    ("Tynemouth", 55.020, -1.450, 275, "gsp", 190),
    ("Hartlepool", 54.690, -1.210, 400, "gsp", 560),
    ("Heysham", 54.030, -2.910, 400, "gsp", 620),
    ("Penwortham", 53.740, -2.730, 400, "gsp", 370),
    ("Padham", 53.790, -2.310, 275, "gsp", 160),
    ("Bradford West", 53.790, -1.790, 275, "gsp", 280),
    ("Thornton", 53.760, -0.300, 275, "gsp", 200),
    ("Keadby", 53.600, -0.750, 400, "gsp", 320),
    ("Drax", 53.740, -0.990, 400, "gsp", 660),
    ("Eggborough", 53.710, -1.120, 400, "gsp", 580),
    ("Monk Fryston", 53.770, -1.260, 400, "gsp", 290),
    ("Osbaldwick", 53.960, -1.030, 275, "gsp", 210),
    ("Wylfa", 53.420, -4.480, 400, "gsp", 250),
    ("Deeside", 53.220, -3.030, 400, "gsp", 310),
    ("Legacy", 53.120, -2.960, 275, "gsp", 220),
    ("Capenhurst", 53.270, -2.950, 275, "gsp", 180),
    ("Frodsham", 53.280, -2.730, 275, "gsp", 260),
    ("Fiddlers Ferry", 53.371, -2.688, 400, "gsp", 440),
    ("Birkenhead", 53.370, -3.020, 275, "gsp", 200),
    ("Kirkby", 53.490, -2.880, 275, "gsp", 320),
    ("Lister Drive", 53.420, -2.940, 275, "gsp", 290),
    ("Washway Farm", 53.420, -2.380, 275, "gsp", 260),
    ("South Manchester", 53.430, -2.240, 400, "gsp", 380),
    ("Stalybridge", 53.490, -2.050, 275, "gsp", 180),
    ("Rochdale", 53.620, -2.150, 275, "gsp", 200),
    ("Whitegate", 53.230, -2.520, 275, "gsp", 150),
    ("Ironbridge", 52.630, -2.490, 400, "gsp", 280),
    ("Bushbury", 52.620, -2.110, 275, "gsp", 310),
    ("Hams Hall", 52.530, -1.680, 400, "gsp", 350),
    ("Berkswell", 52.395, -1.641, 275, "gsp", 260),
    ("Drakelow", 52.780, -1.638, 275, "gsp", 180),
    ("Ratcliffe", 52.860, -1.260, 400, "gsp", 520),
    ("Staythorpe", 53.073, -0.860, 400, "gsp", 390),
    ("West Burton", 53.370, -0.810, 400, "gsp", 480),
    ("Cottam", 53.310, -0.780, 400, "gsp", 460),
    ("High Marnham", 53.210, -0.830, 275, "gsp", 200),
    ("Spalding", 52.790, -0.150, 275, "gsp", 180),
    ("Walpole", 52.750, 0.200, 400, "gsp", 290),
    ("Norwich Main", 52.620, 1.240, 400, "gsp", 320),
    ("Sizewell", 52.220, 1.620, 400, "gsp", 580),
    ("Bramford", 52.070, 1.070, 400, "gsp", 360),
    ("Pelham", 51.950, 0.080, 400, "gsp", 310),
    ("Rye House", 51.760, -0.010, 275, "gsp", 260),
    ("Waltham Cross", 51.690, -0.030, 275, "gsp", 380),
    ("Tottenham", 51.590, -0.070, 275, "gsp", 450),
    ("Hackney", 51.550, -0.050, 275, "gsp", 510),
    ("City Road", 51.530, -0.090, 275, "gsp", 620),
    ("Bankside", 51.508, -0.095, 275, "gsp", 480),
    ("New Cross", 51.475, -0.030, 275, "gsp", 360),
    ("Wimbledon", 51.420, -0.190, 275, "gsp", 290),
    ("Beddington", 51.370, -0.140, 275, "gsp", 260),
    ("Kemsley", 51.360, 0.740, 275, "gsp", 200),
    ("Canterbury", 51.270, 1.080, 275, "gsp", 180),
    ("Sellindge", 51.106, 0.975, 400, "gsp", 220),
    ("Dungeness", 50.920, 0.960, 400, "gsp", 440),
    ("Bolney", 50.975, -0.235, 400, "gsp", 340),
    ("Lovedean", 50.940, -1.040, 400, "gsp", 280),
    ("Fawley", 50.820, -1.330, 400, "gsp", 350),
    ("Mannington", 50.810, -1.870, 400, "gsp", 240),
    ("Exeter", 50.730, -3.510, 275, "gsp", 260),
    ("Hinkley Point", 51.210, -3.130, 400, "gsp", 660),
    ("Bridgwater", 51.130, -3.000, 275, "gsp", 180),
    ("Taunton", 51.020, -3.100, 275, "gsp", 160),
    ("Alverdiscott", 51.020, -3.970, 275, "gsp", 140),
    ("Indian Queens", 50.390, -4.940, 275, "gsp", 200),
    ("Aberthaw", 51.390, -3.400, 275, "gsp", 280),
    ("Swansea North", 51.660, -3.950, 275, "gsp", 240),
    ("Pembroke", 51.680, -4.990, 400, "gsp", 350),
    ("Carmarthen", 51.860, -4.310, 132, "gsp", 120),
    ("Cilfynydd", 51.620, -3.340, 275, "gsp", 280),
    ("Uskmouth", 51.550, -2.960, 275, "gsp", 310),
    ("Seabank", 51.540, -2.660, 400, "gsp", 380),
    ("Melksham", 51.380, -2.140, 400, "gsp", 260),
    ("Didcot", 51.620, -1.260, 400, "gsp", 350),
    ("Culham", 51.660, -1.230, 275, "gsp", 180),
    ("Cowley", 51.750, -1.220, 275, "gsp", 310),
    ("Bramley", 51.339, -1.068, 400, "gsp", 320),
    ("Fleet", 51.280, -0.830, 275, "gsp", 220),
    ("West Weybridge", 51.370, -0.440, 275, "gsp", 350),
    ("Chessington", 51.350, -0.310, 275, "gsp", 290),
    ("West Thurrock", 51.480, 0.280, 275, "gsp", 340),
    ("Tilbury", 51.460, 0.360, 400, "gsp", 380),
    ("Grain", 51.440, 0.720, 400, "gsp", 420),
    ("Barking", 51.530, 0.080, 275, "gsp", 460),
    # === 132kV BSPs and major substations ===
    ("Elgin", 57.650, -3.310, 132, "bsp", 80),
    ("Inverness", 57.480, -4.230, 132, "bsp", 120),
    ("Fort Augustus", 57.150, -4.680, 132, "bsp", 40),
    ("Perth", 56.400, -3.440, 132, "bsp", 140),
    ("Dundee", 56.460, -2.970, 132, "bsp", 160),
    ("St Andrews", 56.340, -2.800, 132, "bsp", 60),
    ("Stirling", 56.120, -3.940, 132, "bsp", 100),
    ("Falkirk", 56.000, -3.780, 132, "bsp", 110),
    ("Livingston", 55.880, -3.520, 132, "bsp", 90),
    ("Edinburgh South", 55.930, -3.190, 132, "bsp", 240),
    ("Galashiels", 55.620, -2.810, 132, "bsp", 50),
    ("Glasgow South", 55.830, -4.260, 132, "bsp", 280),
    ("East Kilbride", 55.760, -4.180, 132, "bsp", 100),
    ("Ayr", 55.460, -4.630, 132, "bsp", 80),
    ("Kilmarnock", 55.610, -4.500, 132, "bsp", 90),
    ("Dumfries", 55.070, -3.610, 132, "bsp", 70),
    ("Carlisle", 54.890, -2.940, 132, "bsp", 110),
    ("Penrith", 54.660, -2.750, 132, "bsp", 40),
    ("Workington", 54.650, -3.540, 132, "bsp", 60),
    ("Barrow", 54.110, -3.230, 132, "bsp", 50),
    ("Lancaster", 54.050, -2.800, 132, "bsp", 80),
    ("Blackpool", 53.820, -3.050, 132, "bsp", 120),
    ("Preston", 53.760, -2.700, 132, "bsp", 150),
    ("Burnley", 53.790, -2.250, 132, "bsp", 80),
    ("Blackburn", 53.750, -2.480, 132, "bsp", 100),
    ("Bolton", 53.580, -2.430, 132, "bsp", 140),
    ("Wigan", 53.550, -2.630, 132, "bsp", 120),
    ("Warrington", 53.390, -2.590, 132, "bsp", 130),
    ("St Helens", 53.450, -2.740, 132, "bsp", 100),
    ("Widnes", 53.360, -2.730, 132, "bsp", 80),
    ("Stockport", 53.410, -2.160, 132, "bsp", 140),
    ("Oldham", 53.540, -2.110, 132, "bsp", 110),
    ("Bury", 53.590, -2.300, 132, "bsp", 100),
    ("Salford", 53.490, -2.290, 132, "bsp", 160),
    ("Trafford Park", 53.460, -2.310, 132, "bsp", 180),
    ("Sunderland", 54.910, -1.380, 132, "bsp", 140),
    ("Durham", 54.780, -1.580, 132, "bsp", 80),
    ("Darlington", 54.530, -1.550, 132, "bsp", 90),
    ("Middlesbrough", 54.580, -1.230, 132, "bsp", 130),
    ("Scarborough", 54.280, -0.400, 132, "bsp", 60),
    ("York", 53.960, -1.080, 132, "bsp", 180),
    ("Harrogate", 53.990, -1.540, 132, "bsp", 70),
    ("Leeds", 53.800, -1.550, 132, "bsp", 340),
    ("Huddersfield", 53.650, -1.780, 132, "bsp", 120),
    ("Wakefield", 53.680, -1.490, 132, "bsp", 110),
    ("Barnsley", 53.550, -1.480, 132, "bsp", 90),
    ("Doncaster", 53.520, -1.130, 132, "bsp", 120),
    ("Sheffield", 53.380, -1.470, 132, "bsp", 280),
    ("Rotherham", 53.430, -1.360, 132, "bsp", 100),
    ("Chesterfield", 53.240, -1.430, 132, "bsp", 80),
    ("Mansfield", 53.140, -1.200, 132, "bsp", 70),
    ("Nottingham", 52.950, -1.150, 132, "bsp", 260),
    ("Derby", 52.920, -1.480, 132, "bsp", 180),
    ("Leicester", 52.630, -1.130, 132, "bsp", 240),
    ("Loughborough", 52.770, -1.200, 132, "bsp", 60),
    ("Lincoln", 53.230, -0.540, 132, "bsp", 80),
    ("Grimsby", 53.570, -0.080, 132, "bsp", 100),
    ("Scunthorpe", 53.590, -0.650, 132, "bsp", 90),
    ("Hull", 53.750, -0.340, 132, "bsp", 200),
    ("Stoke", 53.000, -2.180, 132, "bsp", 160),
    ("Crewe", 53.100, -2.440, 132, "bsp", 60),
    ("Chester", 53.190, -2.890, 132, "bsp", 110),
    ("Wrexham", 53.050, -3.000, 132, "bsp", 70),
    ("Shrewsbury", 52.710, -2.750, 132, "bsp", 80),
    ("Telford", 52.680, -2.440, 132, "bsp", 100),
    ("Wolverhampton", 52.590, -2.130, 132, "bsp", 180),
    ("Walsall", 52.580, -1.980, 132, "bsp", 120),
    ("Birmingham North", 52.510, -1.890, 132, "bsp", 320),
    ("Birmingham South", 52.450, -1.900, 132, "bsp", 280),
    ("Solihull", 52.410, -1.780, 132, "bsp", 140),
    ("Kidderminster", 52.390, -2.250, 132, "bsp", 60),
    ("Worcester", 52.190, -2.220, 132, "bsp", 90),
    ("Redditch", 52.300, -1.940, 132, "bsp", 50),
    ("Stratford", 52.190, -1.710, 132, "bsp", 60),
    ("Northampton", 52.240, -0.900, 132, "bsp", 160),
    ("Corby", 52.490, -0.690, 132, "bsp", 60),
    ("Peterborough", 52.570, -0.240, 132, "bsp", 130),
    ("Kings Lynn", 52.750, 0.400, 132, "bsp", 60),
    ("Cambridge", 52.210, 0.120, 132, "bsp", 150),
    ("Bury St Edmunds", 52.250, 0.720, 132, "bsp", 50),
    ("Ipswich", 52.060, 1.160, 132, "bsp", 120),
    ("Colchester", 51.890, 0.900, 132, "bsp", 100),
    ("Chelmsford", 51.740, 0.470, 132, "bsp", 130),
    ("Southend", 51.540, 0.710, 132, "bsp", 140),
    ("Basildon", 51.570, 0.460, 132, "bsp", 120),
    ("Luton", 51.880, -0.420, 132, "bsp", 160),
    ("Milton Keynes", 52.040, -0.760, 132, "bsp", 180),
    ("Bedford", 52.140, -0.460, 132, "bsp", 80),
    ("Oxford", 51.750, -1.260, 132, "bsp", 150),
    ("Reading", 51.450, -0.970, 132, "bsp", 180),
    ("Swindon", 51.560, -1.780, 132, "bsp", 100),
    ("Gloucester", 51.860, -2.250, 132, "bsp", 100),
    ("Cheltenham", 51.900, -2.070, 132, "bsp", 80),
    ("Bristol", 51.450, -2.590, 132, "bsp", 280),
    ("Bath", 51.380, -2.360, 132, "bsp", 80),
    ("Yeovil", 50.940, -2.630, 132, "bsp", 50),
    ("Weymouth", 50.610, -2.460, 132, "bsp", 40),
    ("Bournemouth", 50.720, -1.880, 132, "bsp", 140),
    ("Poole", 50.720, -1.980, 132, "bsp", 100),
    ("Salisbury", 51.070, -1.800, 132, "bsp", 60),
    ("Southampton", 50.900, -1.400, 132, "bsp", 220),
    ("Portsmouth", 50.800, -1.090, 132, "bsp", 180),
    ("Chichester", 50.840, -0.780, 132, "bsp", 60),
    ("Brighton", 50.830, -0.140, 132, "bsp", 200),
    ("Eastbourne", 50.770, 0.290, 132, "bsp", 80),
    ("Hastings", 50.860, 0.580, 132, "bsp", 60),
    ("Maidstone", 51.270, 0.520, 132, "bsp", 100),
    ("Tunbridge Wells", 51.130, 0.260, 132, "bsp", 70),
    ("Ashford", 51.150, 0.870, 132, "bsp", 60),
    ("Dover", 51.130, 1.310, 132, "bsp", 50),
    ("Thanet", 51.350, 1.410, 132, "bsp", 80),
    ("Chatham", 51.380, 0.520, 132, "bsp", 120),
    ("Dartford", 51.450, 0.210, 132, "bsp", 140),
    ("Croydon", 51.380, -0.100, 132, "bsp", 220),
    ("Bromley", 51.400, 0.020, 132, "bsp", 160),
    ("Lewisham", 51.460, -0.010, 132, "bsp", 180),
    ("Greenwich", 51.480, 0.010, 132, "bsp", 200),
    ("Ilford", 51.560, 0.080, 132, "bsp", 180),
    ("Romford", 51.580, 0.180, 132, "bsp", 130),
    ("Enfield", 51.650, -0.080, 132, "bsp", 160),
    ("Harrow", 51.580, -0.340, 132, "bsp", 150),
    ("Uxbridge", 51.540, -0.480, 132, "bsp", 110),
    ("Hounslow", 51.470, -0.360, 132, "bsp", 140),
    ("Richmond", 51.460, -0.300, 132, "bsp", 120),
    ("Guildford", 51.240, -0.570, 132, "bsp", 100),
    ("Woking", 51.320, -0.560, 132, "bsp", 90),
    ("Basingstoke", 51.270, -1.090, 132, "bsp", 70),
    ("Newbury", 51.400, -1.320, 132, "bsp", 50),
    ("Slough", 51.510, -0.590, 132, "bsp", 120),
    ("High Wycombe", 51.630, -0.750, 132, "bsp", 80),
    ("Aylesbury", 51.820, -0.810, 132, "bsp", 60),
    ("Banbury", 52.060, -1.340, 132, "bsp", 50),
    ("Coventry", 52.410, -1.510, 132, "bsp", 200),
    ("Rugby", 52.370, -1.260, 132, "bsp", 50),
    ("Warwick", 52.280, -1.580, 132, "bsp", 60),
    ("Plymouth", 50.370, -4.140, 132, "bsp", 180),
    ("Torquay", 50.460, -3.530, 132, "bsp", 80),
    ("Barnstaple", 51.080, -4.060, 132, "bsp", 40),
    ("Truro", 50.260, -5.050, 132, "bsp", 70),
    ("Penzance", 50.120, -5.530, 132, "bsp", 40),
    ("Newquay", 50.420, -5.080, 132, "bsp", 50),
    ("Aberystwyth", 52.420, -4.080, 132, "bsp", 30),
    ("Llandrindod", 52.240, -3.380, 132, "bsp", 20),
    ("Newtown", 52.510, -3.310, 132, "bsp", 30),
    ("Bangor", 53.230, -4.130, 132, "bsp", 60),
    ("Caernarfon", 53.140, -4.270, 132, "bsp", 30),
    ("Rhyl", 53.320, -3.490, 132, "bsp", 50),
    ("Newport", 51.590, -3.000, 132, "bsp", 130),
    ("Cardiff", 51.480, -3.180, 132, "bsp", 250),
    ("Barry", 51.400, -3.270, 132, "bsp", 60),
    ("Neath", 51.660, -3.810, 132, "bsp", 70),
    ("Llanelli", 51.680, -4.160, 132, "bsp", 50),
    ("Haverfordwest", 51.800, -4.970, 132, "bsp", 40),
    ("Boston", 52.980, -0.020, 132, "bsp", 40),
    ("Grantham", 52.910, -0.640, 132, "bsp", 40),
    ("Skegness", 53.140, 0.340, 132, "bsp", 30),
    ("Whitby", 54.490, -0.620, 132, "bsp", 30),
    ("Kendal", 54.330, -2.740, 132, "bsp", 40),
    ("Hexham", 54.970, -2.100, 132, "bsp", 30),
    ("Alnwick", 55.410, -1.710, 132, "bsp", 30),
    ("Berwick", 55.770, -2.010, 132, "bsp", 30),
    ("Aberdeen", 57.150, -2.100, 132, "bsp", 200),
    ("Fraserburgh", 57.690, -2.010, 132, "bsp", 30),
    ("Keith", 57.550, -2.950, 132, "bsp", 20),
    ("Fort William", 56.820, -5.110, 132, "bsp", 30),
    ("Oban", 56.420, -5.470, 132, "bsp", 25),
    ("Pitlochry", 56.700, -3.730, 132, "bsp", 20),
    ("Arbroath", 56.560, -2.590, 132, "bsp", 30),
    ("Kirkcaldy", 56.110, -3.170, 132, "bsp", 80),
    ("Alloa", 56.120, -3.790, 132, "bsp", 40),
    ("Hamilton", 55.780, -4.040, 132, "bsp", 90),
    ("Motherwell", 55.790, -3.990, 132, "bsp", 80),
    ("Greenock", 55.950, -4.760, 132, "bsp", 60),
    ("Irvine", 55.610, -4.670, 132, "bsp", 50),
    ("Cumbernauld", 55.950, -3.990, 132, "bsp", 50),
    ("Dunfermline", 56.070, -3.430, 132, "bsp", 70),
    # === Bridge nodes (fix Scotland disconnect) + missing major substations ===
    ("Tealing", 56.510, -3.010, 275, "gsp", 180),    # Kintore-Tealing-Dundee link
    ("Denny", 56.020, -3.910, 275, "gsp", 220),       # Beauly-Denny 400kV line terminus
    ("Tummel Bridge", 56.720, -3.970, 132, "bsp", 40), # Hydro generation
    # === Missing major generation substations ===
    ("Dinorwig", 53.120, -4.120, 400, "gsp", 1700),   # 1.7GW pumped-storage hydro
    ("Cruachan", 56.400, -5.110, 275, "gsp", 440),    # 440MW pumped-storage hydro
    ("Lackenby", 54.567, -1.132, 275, "gsp", 360),    # Teesside steel / industry
    ("Killingholme", 53.650, -0.220, 275, "gsp", 300), # South Humber gas generation
    # === Missing 400kV ring nodes ===
    ("Sundon", 51.930, -0.470, 400, "gsp", 280),      # North London 400kV ring
    ("Elstree", 51.650, -0.290, 275, "gsp", 340),     # North London 400kV ring
    ("Littlebrook", 51.460, 0.240, 275, "gsp", 300),   # Thames estuary
    ("Nursling", 50.950, -1.470, 400, "gsp", 260),    # South coast
    ("Ninfield", 50.870, 0.400, 275, "gsp", 180),     # South coast
    ("Cellarhead", 53.030, -1.990, 275, "gsp", 200),  # Staffordshire
    ("Grendon", 52.280, -0.870, 400, "gsp", 240),     # Midlands ring
    ("Stanah", 53.870, -2.980, 275, "gsp", 180),      # Lancashire
]


def _haversine(lat1, lon1, lat2, lon2):
    """Distance in km between two points."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def build_topology():
    """Build node + edge topology for the UK national grid.

    Returns:
        nodes: list of dicts with id, name, lat, lon, voltage_kv, node_type, demand_mw
        edges: list of dicts with from_id, to_id, flow_mw, capacity_mva, utilization
    """
    # De-duplicate nodes by name (some appear twice)
    seen = set()
    nodes = []
    for name, lat, lon, voltage, ntype, demand in _GRID_NODES_RAW:
        if name in seen:
            continue
        seen.add(name)
        nodes.append({
            "id": f"N{len(nodes):03d}",
            "name": name,
            "lat": lat,
            "lon": lon,
            "voltage_kv": voltage,
            "node_type": ntype,
            "demand_mw": demand,
        })

    # Build edges using nearest-neighbour connectivity
    # Strategy: each node connects to its K nearest neighbours
    # GSPs (400/275kV) connect to more nodes; BSPs connect to fewer
    edges = []
    edge_set = set()

    for i, n in enumerate(nodes):
        # Calculate distances to all other nodes
        dists = []
        for j, m in enumerate(nodes):
            if i == j:
                continue
            d = _haversine(n["lat"], n["lon"], m["lat"], m["lon"])
            dists.append((d, j))
        dists.sort()

        # GSPs connect to 3-5 nearest, BSPs to 2-3 nearest
        k = random.randint(3, 5) if n["node_type"] == "gsp" else random.randint(2, 3)
        # Only connect to nodes within reasonable distance
        max_dist = 120 if n["voltage_kv"] >= 275 else 60

        for d, j in dists[:k]:
            if d > max_dist:
                break
            edge_key = tuple(sorted((i, j)))
            if edge_key in edge_set:
                continue
            edge_set.add(edge_key)

            m = nodes[j]
            # Flow proportional to average demand, with some noise
            avg_demand = (n["demand_mw"] + m["demand_mw"]) / 2
            flow = max(5, avg_demand * random.uniform(0.3, 0.9))
            capacity = max(flow * 1.2, min(n["voltage_kv"], m["voltage_kv"]) * random.uniform(0.5, 1.5))
            utilization = round(flow / capacity, 3) if capacity > 0 else 0

            edges.append({
                "from_id": n["id"],
                "to_id": m["id"],
                "from_name": n["name"],
                "to_name": m["name"],
                "flow_mw": round(flow, 1),
                "capacity_mva": round(capacity, 1),
                "utilization": min(utilization, 1.0),
                "voltage_kv": min(n["voltage_kv"], m["voltage_kv"]),
            })

    # ── Ensure graph connectivity: add strategic bridge edges ──
    # These represent real transmission circuits that the nearest-neighbour
    # algorithm misses due to distance constraints.
    name_to_idx = {n["name"]: i for i, n in enumerate(nodes)}
    STRATEGIC_BRIDGES = [
        # Beauly-Denny 400kV line (critical Scotland N-S link)
        ("Beauly", "Denny"),
        # Kintore-Tealing 275kV (east coast Scotland link)
        ("Kintore", "Tealing"),
        # Tealing-Dundee-Perth chain
        ("Tealing", "Dundee"),
        ("Perth", "Denny"),
        # Fort William-Cruachan hydro link
        ("Fort William", "Cruachan"),
        # Cruachan-Stirling via Dalmally circuit
        ("Cruachan", "Stirling"),
        # Dounreay-Beauly (north Highland)
        ("Dounreay", "Beauly"),
        # Dinorwig-Deeside (Welsh pumped-storage export)
        ("Dinorwig", "Deeside"),
        # Lackenby-Hartlepool (Teesside)
        ("Lackenby", "Hartlepool"),
        # Humberside links (Thornton/Killingholme to Keadby)
        ("Killingholme", "Keadby"),
        ("Thornton", "Keadby"),
    ]

    for from_name, to_name in STRATEGIC_BRIDGES:
        i = name_to_idx.get(from_name)
        j = name_to_idx.get(to_name)
        if i is None or j is None:
            continue
        edge_key = tuple(sorted((i, j)))
        if edge_key in edge_set:
            continue
        edge_set.add(edge_key)
        n, m = nodes[i], nodes[j]
        avg_demand = (n["demand_mw"] + m["demand_mw"]) / 2
        flow = max(20, avg_demand * random.uniform(0.4, 0.8))
        capacity = max(flow * 1.3, min(n["voltage_kv"], m["voltage_kv"]) * random.uniform(0.6, 1.2))
        utilization = round(flow / capacity, 3) if capacity > 0 else 0
        edges.append({
            "from_id": n["id"], "to_id": m["id"],
            "from_name": n["name"], "to_name": m["name"],
            "flow_mw": round(flow, 1),
            "capacity_mva": round(capacity, 1),
            "utilization": min(utilization, 1.0),
            "voltage_kv": min(n["voltage_kv"], m["voltage_kv"]),
        })

    return nodes, edges


_CACHED_GEOJSON = None


def topology_to_geojson():
    """Return full UK grid topology as GeoJSON FeatureCollections (cached)."""
    global _CACHED_GEOJSON
    if _CACHED_GEOJSON is not None:
        return _CACHED_GEOJSON

    nodes, edges = build_topology()

    node_lookup = {n["id"]: n for n in nodes}

    node_features = []
    for n in nodes:
        node_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [n["lon"], n["lat"]]},
            "properties": {
                "node_id": n["id"],
                "name": n["name"],
                "node_type": n["node_type"],
                "voltage_kv": n["voltage_kv"],
                "demand_mw": n["demand_mw"],
            },
        })

    flow_features = []
    for e in edges:
        fn = node_lookup[e["from_id"]]
        tn = node_lookup[e["to_id"]]
        flow_features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[fn["lon"], fn["lat"]], [tn["lon"], tn["lat"]]],
            },
            "properties": {
                "comp_id": f"{e['from_id']}-{e['to_id']}",
                "from_node": e["from_name"],
                "to_node": e["to_name"],
                "flow_mw": e["flow_mw"],
                "capacity_mva": e["capacity_mva"],
                "utilization": e["utilization"],
                "voltage_kv": e["voltage_kv"],
            },
        })

    _CACHED_GEOJSON = {
        "nodes": {"type": "FeatureCollection", "features": node_features},
        "flows": {"type": "FeatureCollection", "features": flow_features},
    }
    return _CACHED_GEOJSON
