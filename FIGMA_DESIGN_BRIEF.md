# Feasibly — Comprehensive Figma Design Brief

## For: VC Pitch Deck Sample UI Screens + Complete Product Documentation

> Every measurement, color, and text string below is extracted directly from the production codebase.
> All screens use **IBM Plex Mono** exclusively. Dark theme only. No light mode.

---

# PART 1: DESIGN SYSTEM

## 1.1 CSS Custom Properties (Root Variables)

```
--mono:           "IBM Plex Mono", monospace
--bg:             #0a0e14
--surface:        rgba(22, 22, 22, 0.95)
--glass:          rgba(22, 22, 22, 0.85)
--glass-bg:       rgba(22, 22, 22, 0.85)
--glass-border:   rgba(82, 82, 82, 0.3)
--border:         rgba(82, 82, 82, 0.2)
--text:           #c6c6c6
--text-bright:    #f4f4f4
--text-dim:       #8d8d8d
--accent:         #0f62fe
--accent-dim:     rgba(15, 98, 254, 0.6)
--purple:         #7c4dff
--danger:         #ff1744
--warn:           #ff9100
--shadow:         0 4px 24px rgba(0, 0, 0, 0.4)
```

### Carbon Design System Tokens (IBM Carbon Dark)
```
--cds-background:      #161616
--cds-layer-01:        #262626
--cds-layer-02:        #393939
--cds-interactive:     #0f62fe
--cds-text-primary:    #f4f4f4
--cds-text-secondary:  #c6c6c6
--cds-text-helper:     #8d8d8d
--cds-border-subtle:   #525252
--cds-support-success: #24a148
--cds-support-warning: #f1c21b
--cds-support-error:   #da1e28
```

## 1.2 Complete Color Palette

### Primary Backgrounds
| Token | Value | Usage |
|-------|-------|-------|
| Page BG | `#161616` | Main app background |
| Layer 01 | `#262626` | Header, command bar, elevated surfaces |
| Layer 02 | `#393939` | Inputs, secondary surfaces, hover states |
| Glass BG | `rgba(22, 22, 22, 0.85)` | Floating cards, overlays, popovers |
| Dark Surface | `rgba(38, 38, 38, 0.5)` | Card insets, stat boxes |
| Pitch BG | `#0d0d0d` | Pitch page background |

### Interactive Colors
| Token | Value | Usage |
|-------|-------|-------|
| Interactive | `#0f62fe` | Primary buttons, links, brand accent |
| Interactive Dark | `#0043ce` | Hover states |
| Interactive 12% | `rgba(15, 98, 254, 0.12)` | Active tab backgrounds |
| Interactive 8% | `rgba(15, 98, 254, 0.08)` | Hover backgrounds |

### Text Colors
| Token | Value | Usage |
|-------|-------|-------|
| Primary | `#f4f4f4` | Headings, important values |
| Secondary | `#c6c6c6` | Body text |
| Helper | `#8d8d8d` | Labels, captions, dim text |

### Status / Semantic Colors
| Token | Value | Usage |
|-------|-------|-------|
| GO / Success | `#4caf50` | Positive verdicts, good scores |
| CAUTION / Warning | `#ff9800` | Warnings, moderate scores |
| NO-GO / Error | `#f44336` | Negative verdicts, failures |
| Success Alt | `#24a148` | Carbon success (layer toggles, KPI) |
| Warning Alt | `#f1c21b` | Carbon warning (yield metrics) |
| Error Alt | `#da1e28` | Carbon error |

### Accent Colors (by metric type — consistent across all views)
| Metric | Color | Hex |
|--------|-------|-----|
| Solar / Yield | Orange | `#ff9800` |
| Capacity Factor | Cyan | `#00e5ff` |
| Score | Green | `#4caf50` / `#24a148` |
| Grid | Blue | `#2196f3` |
| Confidence | Purple | `#a56eff` / `#7c4dff` |
| Financial | Orange | `#ff9800` |
| Environmental | Teal | `#009688` |
| Terrain | Blue | `#2196f3` |
| Storage | Cyan | `#00bcd4` |
| Planning | Pink | `#e91e63` |
| Satellite | Dark Blue | `#1565c0` |
| Legacy | Slate | `#607d8b` |
| Procurement | Deep Orange | `#ff5722` |
| Grid Efficiency | Brown | `#795548` |
| Prospector | Teal | `#009688` |
| BESS | Green | `#4caf50` |
| Home Retrofit | Purple | `#8e24aa` |
| Land Classifier | Deep Orange | `#ff6f00` |
| Stability | Dynamic | Green/Orange/Red by risk |

### Energy Asset Colors (Map markers)
| Type | Color |
|------|-------|
| Solar | `#fdd835` (yellow) |
| Wind | `#00b0ff` (cyan) |
| Gas | `#ff8f00` (orange) |
| Nuclear | `#e53935` (red) |
| Hydro | `#1565c0` (blue) |
| Battery | `#7cb342` (green) |
| Substation | `#78909c` (grey) |

### Verdict Badge Colors
| Verdict | BG | Glow |
|---------|----|----|
| GO | `#4caf50` | `0 0 20px rgba(76, 175, 80, 0.4)` |
| CAUTION | `#ff9800` | `0 0 20px rgba(255, 152, 0, 0.4)` |
| NO-GO | `#da1e28` | `0 0 20px rgba(218, 30, 40, 0.4)` |

### Chat Message Colors
| Role | Background | Border |
|------|-----------|--------|
| User | `rgba(124, 77, 255, 0.12)` | `rgba(124, 77, 255, 0.15)` |
| Assistant | `rgba(0, 229, 255, 0.05)` | `rgba(0, 229, 255, 0.08)` |
| System | `rgba(255, 145, 0, 0.08)` | `rgba(255, 145, 0, 0.1)` |

## 1.3 Typography Scale

**Font Family**: `"IBM Plex Mono", monospace` — used for ALL text, no exceptions.

| Usage | Size | Weight | Case | Letter-Spacing | Line-Height |
|-------|------|--------|------|----------------|-------------|
| Hero Title (Pitch) | 72px | 800 | — | 12px | — |
| Big Stat Number | 32px | 800 | — | — | — |
| Pitch Slide Title | 28px | 800 | UPPER | 3px | — |
| Pitch Stat Value | 28px | 800 | — | — | — |
| Stage Number | 20px | 800 | — | — | — |
| Pitch Sub | 16px | — | — | — | 1.6 |
| Brand Logo | 14px | 800 | UPPER | 3px | — |
| KPI Value | 14px | 700 | — | — | — |
| Compliance Code | 14px | 800 | — | — | — |
| Stage Title | 14px | 800 | — | 2px | — |
| Lead Text | 14px | — | — | — | 1.6 |
| Body / Pain Text | 13px | 700 | — | — | — |
| Card Value | 12px | 700 | — | — | — |
| Body | 12px | 600 | — | — | 1.55 |
| Chat Message | 12px | — | — | — | 1.55 |
| Feature Text | 12px | 700 | — | — | — |
| Section Head | 11px | 800 | UPPER | 2px | — |
| Hero Eyebrow | 11px | 700 | UPPER | 4px | — |
| Tab | 11px | 700 | UPPER | — | — |
| Flow Step | 11px | 700 | UPPER | 1px | — |
| Model Name | 11px | 700 | — | — | — |
| Back Button | 11px | 600 | — | — | — |
| Slide Counter | 11px | 600 | — | — | — |
| Paint Icon | 11px | 800 | — | — | — |
| Stage Items | 10px | — | — | — | 1.4 |
| KPI Label | 10px | 700 | UPPER | — | — |
| Domain Detail | 10px | — | — | — | 1.4 |
| Replaces Label | 10px | 700 | UPPER | 2px | — |
| Revenue Label | 10px | 600 | — | — | — |
| Button | 10px | 700 | UPPER | 0.5px | — |
| Table Row | 10px | — | — | — | — |
| Micro Label | 9px | 700 | UPPER | 1-2px | — |
| Intent Chip | 9px | 700 | UPPER | 0.5px | — |
| Chat Label | 9px | 700 | UPPER | 1px | — |
| Pitch Dot Label | 8px | — | — | — | — |

## 1.4 Shared Elements

### Glass Card
```
background: rgba(22, 22, 22, 0.85)
backdrop-filter: blur(12px)
-webkit-backdrop-filter: blur(12px)
border: 1px solid rgba(82, 82, 82, 0.3)
border-radius: 8px
padding: 12px
box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4)
animation: slideIn 0.4s ease-out
```

### Metric Card (Floating Card)
```
background: var(--glass-bg)
backdrop-filter: blur(12px)
border: 1px solid var(--glass-border)
border-radius: 8px
padding: 12px
box-shadow: var(--shadow)
```
Header row: `.metric-card-header` — flex row with:
- Colored dot (8px circle, card accent color, `box-shadow: 0 0 6px {color}40`)
- Title text (11px, weight 800, uppercase, letter-spacing 2px, color `#8d8d8d`)
- Collapse chevron (right-aligned, 10px)

### Button Primary
```
background: #0f62fe
color: white
font: 10px/700 IBM Plex Mono
text-transform: uppercase
letter-spacing: 0.5px
padding: 4px 10px
border-radius: 2px
border: none
cursor: pointer
transition: background 0.15s
hover: background #0043ce
```

### Button Ghost
```
background: transparent
border: 1px solid rgba(255, 255, 255, 0.12)
color: #8d8d8d
font: 10px/700 IBM Plex Mono
padding: 4px 10px
border-radius: 2px
hover: border-color #0043ce, color #c6c6c6
```

### Input Field
```
background: #393939
border: 1px solid #525252
color: #f4f4f4
font: 13px IBM Plex Mono
padding: 8px 10px
border-radius: 3px
outline: none
focus: border-color #0f62fe
placeholder-color: #8d8d8d
```

### Verdict Badge
```
font: 16px/800 IBM Plex Mono
letter-spacing: 3px
padding: 10px 28px
border: 2px solid {verdict-color}
border-radius: 4px
color: white
background: {verdict-color}
box-shadow: 0 0 20px {verdict-color}40
```

### Imagery Badge (satellite detection indicator)
```
display: inline-flex
padding: 3px 10px
border-radius: 12px
font: 11px/600 IBM Plex Mono
color: #64b5f6
background: rgba(100, 181, 246, 0.1)
border: 1px solid rgba(100, 181, 246, 0.2)
```

## 1.5 Animations & Keyframes

| Name | Description | Duration | Properties |
|------|-------------|----------|------------|
| `card-slide-in` | Card entrance | 0.4s ease-out | opacity 0→1, translateX(20px→0) |
| `popover-slide-up` | Chat popover | 0.2s ease-out | opacity 0→1, translateY(12px→0) |
| `spin` | Loading spinners | 1s linear infinite | rotate(0→360deg) |
| `ai-pulse` | AI status dot | 2s ease-in-out infinite | opacity 1→0.4→1 |
| `pulse-pick` | Map pick mode | 2s ease-in-out infinite | box-shadow radius 0→8px |
| `sd-fade-in` | Dashboard entrance | 0.3s ease-out | opacity 0→1 |
| `sp-pop-in` | Site picker entrance | 0.3s ease-out | opacity 0→1, scale(0.95→1) |
| `sp-pulse` | Site picker dot | 2s ease-in-out infinite | box-shadow radial expand |
| `chat-spin` | Tool execution | 1s linear infinite | rotate(0→360deg) |
| `pitch-fade-in` | Slide transition | 0.3s ease | opacity 0→1, translateY(12px→0) |
| `settings-toast-in` | Toast notification | 0.2s ease-out | opacity 0→1, translateY(8px→0) |

---

# PART 2: GLOBAL LAYOUT ARCHITECTURE

## 2.1 App Grid (3-Row Layout)

```
.app-grid-v2 {
  display: grid;
  grid-template-rows: auto 1fr 44px;
  grid-template-columns: 1fr;
  grid-template-areas:
    "header"
    "map"
    "cmdbar";
  height: 100vh;
  width: 100%;
  background: var(--cds-background);
  overflow: hidden;
}
```

### ASCII Layout
```
┌─────────────────────────────────────────────────────────────────┐
│ HEADER (auto height ~48px)                          z-index: 20│
│ Brand | Breadcrumbs | Study Sub-Nav | KPI Strip | Actions      │
├─────────────────────────────────────────────────────────────────┤
│ MAP AREA (1fr — fills remaining height)             z-index: 0 │
│                                                                 │
│  ┌─Layer Rail──┐                        ┌─Floating Cards──┐   │
│  │ (left:8px)  │                        │ (right:8px)      │   │
│  │ z:15        │     3D MAPBOX          │ width:380px      │   │
│  │ 54px icons  │     (pitch 45°)        │ z:5              │   │
│  │ +220px fly  │                        │ Scroll vertical  │   │
│  └─────────────┘                        └──────────────────┘   │
│                                                                 │
│  ┌─Draw Toolbar─┐   ┌─AI Top Banner (over map)────────────┐   │
│  │ (left:12px)   │   │ 40px, z:20, dark blur               │   │
│  │ z:10          │   └─────────────────────────────────────┘   │
│  └───────────────┘   ┌─AI Bottom Bar (over map)────────────┐   │
│                      │ 28px, z:20, dark blur                │   │
│  ┌─Component────┐   └─────────────────────────────────────┘   │
│  │ Palette      │                                              │
│  │ (PLAN only)  │                                              │
│  │ left:12px    │                                              │
│  │ top:400px    │                                              │
│  │ width:240px  │                                              │
│  └──────────────┘                                              │
├─────────────────────────────────────────────────────────────────┤
│ COMMAND BAR (44px)                                  z-index: 10│
│ [AI History] [Attach] [________Chat Input________] [Send]      │
└─────────────────────────────────────────────────────────────────┘
```

## 2.2 Z-Index Stacking Order

| Z-Index | Component |
|---------|-----------|
| 2000 | Pitch Page overlay (full-screen) |
| 2000 | Settings Page overlay (full-screen) |
| 2000 | NOM Explorer overlay (full-screen) |
| 1000 | Digital Twin overlay (full-screen) |
| 100 | Site Dashboard overlay |
| 50 | Chat history popover |
| 20 | Header Bar |
| 20 | AI Top Banner / Bottom Bar |
| 15 | Layer Rail (icons + flyout) |
| 10 | Command Bar |
| 10 | Drawing Toolbar |
| 10 | Component Palette |
| 5 | Floating Cards |
| 0 | Mapbox GL (base) |

## 2.3 Critical Dimensions Reference

| Component | Width | Height | Position | Notes |
|-----------|-------|--------|----------|-------|
| Header | 100% | ~48px | top: 0, full width | Flex row |
| Map Container | 100% | calc(100vh - 92px) | Below header | Relative container |
| Command Bar | 100% | 44px | bottom: 0 | Grid area: cmdbar |
| Floating Cards | 380px | 100% - 16px | right: 8px, top: 8px | Scrollable |
| Layer Rail Icons | 54px | auto | left: 8px, top: 8px | Vertical strip |
| Layer Rail Flyout | 220px | max calc(100vh-120px) | left: 54px relative | Scrollable |
| Drawing Toolbar | 44px+ | auto | left: 12px, top: 12px | Vertical |
| Component Palette | 240px | max calc(100vh-420px) | left: 12px, top: 400px | PLAN stage only |
| Chat History | 500px | max 600px | left: 10px, bottom: 48px | Popover |
| Site Dashboard | max 1400px (90vw) | max 90vh | Centered overlay | 3-col grid |
| AI Top Banner | 100% | 40px | top of map area | Blur overlay |
| AI Bottom Bar | 100% | 28px | bottom of map area | Blur overlay |
| Site Picker | 380px | auto | Centered | Modal |

---

# PART 3: SCREEN-BY-SCREEN MOCKUP SPECIFICATIONS

## SCREEN 1: HERO — Main App View (Study Stage)

> **Purpose**: Full product in action — site selected, map visible, verdict displayed.
> **Figma frame**: 1440 x 900 (16:9)

### Header Bar (48px, `#262626` bg, border-bottom `rgba(82,82,82,0.3)`)

**Left section** (flex, gap: 12px):
- **Brand**: "FEASIBLY" — 14px, weight 800, `#0f62fe`, letter-spacing 3px
- **Breadcrumb**: `SITE > STUDY > PLAN > ACT`
  - Active "STUDY": `#0f62fe` bg, white text, 4px radius
  - Visited "SITE": `#8d8d8d` text, `#525252` border
  - Locked "PLAN", "ACT": `#525252` text, dashed border, opacity 0.5
  - Separator `>`: `#8d8d8d`, 10px

**Study Sub-nav** (flex, gap: 4px):
- 7 buttons: `Feasibility` | `Grid` | `Financial` | `Environ.` | `Satellite` | `Legacy` | `BESS`
- Active: `rgba(15, 98, 254, 0.15)` bg, `#0f62fe` text, `#0f62fe` border-bottom 2px
- Inactive: transparent, `#8d8d8d` text
- Font: 11px, weight 600, uppercase
- Padding: 6px 10px

**Right section** (flex, gap: 8px, margin-left: auto):

**KPI Strip** (6 metric cells, flex row, gap: 12px):
Each cell is a flex column:
- Label: 10px, weight 700, uppercase, `#8d8d8d`
- Value: 14px, weight 700, colored

| Label | Value | Color |
|-------|-------|-------|
| YIELD | 5.5 MWh | `#f1c21b` (warning yellow) |
| CF | 10.9% | `#0f62fe` (interactive blue) |
| SCORE | 98 | `#24a148` (success green) |
| GRID | 1.8km | `#2196f3` (info blue) |
| VERDICT | GO | `#4caf50` (green) |
| CONF | 87% | `#a56eff` (purple) |

**SAM Capacity Input**: `[100] kW` — number input, 50px width, `#393939` bg
**Action Buttons**: "PITCH" "NOM" + gear icon — ghost style buttons

---

### Map Viewport (fills remaining space)

- **Basemap**: Mapbox Dark style (CartoDB dark raster + custom terrain)
- **3D Terrain**: Enabled with exaggeration 2.0, GBDEM DTM raster-dem source
- **Camera**: pitch 45°, bearing -10°, center on site
- **Hillshade**: Green accent tint, subtle terrain shading
- **Sky**: Atmosphere enabled, blue tint at horizon
- **Fog**: Subtle depth fog for aerial perspective

**Map Markers & Overlays**:
- Blue dashed polygon: Site boundary (~12ha field outline)
- Yellow crosshair marker: Nearest substation (1.8km away)
- Dashed yellow line: Cable route from site to substation
- Energy asset circles: Color-coded by type (see color table), radius scales with capacity

---

### AI Top Banner (40px, over map top edge)
```
position: absolute; top: 0; width: 100%;
height: 40px;
background: rgba(6, 10, 15, 0.94);
backdrop-filter: blur(16px);
border-bottom: 1px solid rgba(82, 82, 82, 0.15);
z-index: 20;
```

**Layout**: Flex row, 3 sections:

**Left** (flex, gap: 8px):
- Green pulsing dot (8px, `#4caf50`, animation: `ai-pulse 2s infinite`)
- "GO" text (11px, weight 800, `#4caf50`)
- "AI ASSESSMENT" (9px, weight 600, `#8d8d8d`, uppercase, letter-spacing 1px)

**Center** (flex, gap separated by 1px `rgba(82,82,82,0.2)` dividers):
6 metric cells (each flex column):
| Label | Value |
|-------|-------|
| SOLAR YIELD | 5.5 MWh/yr |
| CAPACITY FACTOR | 10.9% |
| GRID STABILITY | 94% |
| FORECAST | 42 kWh/d |
| SITE SCORE | 98/120 |
| LAND SCORE | 82/100 |

Labels: 7px, weight 700, uppercase, letter-spacing 1px, `#525252`
Values: 12px, weight 700, colored by metric type

**Right** (flex-end):
- Italic summary: "Site demonstrates strong feasibility..." — 10px, `#8d8d8d`, italic, truncated

---

### AI Bottom Bar (28px, over map bottom edge)
```
position: absolute; bottom: 0; width: 100%;
height: 28px;
background: rgba(6, 10, 15, 0.92);
backdrop-filter: blur(12px);
border-top: 1px solid rgba(82, 82, 82, 0.1);
```

10 cells with micro labels + values:
| Label | Value | Notes |
|-------|-------|-------|
| ZULU | 14:32:08Z | UTC time |
| GRID REF | 51.8800N 1.1600W | Coordinates |
| SELF-SUFF | 72% | Self-sufficiency |
| TURBINE | NF | No fault |
| TX LINES | 94% OK | Transmission |
| ENERGY | 5.5p/kWh | Price |
| GRID CONN | 1.8km | Distance |
| DEFERRAL | 2 ALLOC | Allocations |
| PARCEL | BICESTER- | Truncated ID |

Labels: 7px, weight 700, uppercase, `#525252`
Values: 10px, weight 600, `#c6c6c6`

---

### Layer Rail (left side, over map)

**Icon Column** (vertical, glass bg):
```
position: absolute; top: 8px; left: 8px; z-index: 15;
```
- 5 section icons as 36x36px buttons
- Glass background with blur
- Vertical gap: 2px
- Each icon has colored indicator dot when section contains active layers

**5 Section Icons** (top to bottom):
1. **Terrain** (mountain icon) — brown `#8d6e63`
   - Hillshade, Slope (with opacity slider), Contours, LIDAR DTM, LIDAR DSM
2. **Grid** (lightning icon) — blue `#0f62fe`
   - Grid Flow, Agile Pricing, Smart Meter, Flow Focus, OSM Power, NGED Subs, Elec. Zones
3. **Land** (tree icon) — green `#24a148`
   - Carbon, LA Boundaries, Transport, Energy Assets, Land Use (GEE), Grid Opportunities
4. **Remote** (satellite icon) — purple `#a56eff`
   - NDVI, Sentinel-2, Aerial (ESRI), Landsat, VIIRS Daily
5. **EPC** (house icon) — orange `#f1c21b`
   - Neighbourhoods, Domestic EPC, Non-Dom EPC, Postcodes Energy

**Flyout Panel** (appears on icon click):
- Width: 220px, glass bg, blur(20px), 8px radius
- Layer items: Checkbox + colored dot (8px) + label (11px)
- Optional: opacity slider (for slope), dropdown select (for EPC field)
- **AI Layers** section at bottom (from chat): colored dot + name + `x` remove button

---

### Floating Cards (right panel, 380px width)

**Container**:
```
position: absolute; top: 8px; right: 8px; bottom: 8px;
width: 380px; gap: 6px;
overflow-y: auto;
```

**Card 1: Agent Verdict** (top)
- Glass card, 8px radius
- **Verdict Badge**: "GO" — `#4caf50` bg, white text, 16px weight 800, pill-rounded, glow `0 0 20px rgba(76,175,80,0.4)`
- **Confidence**: "87% confidence" — 12px, `#a56eff`
- **Intent Tag**: "FEASIBILITY" — 9px, uppercase, `#0f62fe`
- **Summary**: 2-line text, 12px, `#c6c6c6`, line-height 1.55

**Card 2: Score Card** (accent: `#4caf50`)
- Header: colored dot + "SCORE" label
- Badge: "98/120" — 14px, weight 700, color by percentage (>70% = green)
- 4 horizontal score bars:
  - Resource: 27/30 — `#4caf50` fill
  - Grid: 24/30 — `#2196f3` fill
  - Planning: 23/30 — `#ff9800` fill
  - Environment: 24/30 — `#4caf50` fill
- Each bar: height 6px, `#333` track bg, colored fill, border-radius 3px

**Card 3: Solar Card** (accent: `#ff9800`)
- Header: orange dot + "SOLAR"
- Hero value: "5,475 kWh/yr" — 14px, weight 700
- Sub: "10.9% CF" — 12px, `#ff9800`
- **Monthly bar chart** (12 bars):
  - Values (kWh): 215k, 285k, 425k, 540k, 610k, 630k, 625k, 570k, 450k, 325k, 220k, 180k
  - Bar color: `#4caf50`
  - Labels: J F M A M J J A S O N D (10px)
  - Height proportional to max value

**Card 4: Terrain Card** (accent: `#2196f3`)
- Slope stats: Mean 2.8°, Min 0°, Max 8.3°
- Slope histogram bar chart (`#2196f3` bars)
- Imagery badge: "Flat terrain confirmed" (blue pill)

**Card 5: Grid Context Card** (accent: `#00bcd4`)
- 24h demand bar chart (cyan `#00bcd4` bars)
- Solar generation bars (`#ff9800`)
- Curtailment risk bars (color by risk: >0.5 red, 0.25-0.5 orange, <0.25 green)
- Weather: 10.8°C, 58% cloud, 1045 W/m²

---

### Command Bar (bottom, 44px, `#262626` bg)
```
height: 44px; padding: 0 10px;
border-top: 1px solid rgba(82, 82, 82, 0.3);
display: flex; align-items: center; gap: 6px;
```

- **AI History btn** (left): 32x32, chat icon SVG, badge shows message count
- **Attach btn**: 32x32, paperclip icon, `#525252` border
- **Chat input**: flex-fill, `rgba(0,0,0,0.2)` bg, `#525252` border, 12px mono, placeholder "Ask about this site's feasibility..."
- **Send btn** (right): 32x32, `rgba(0,229,255,0.1)` bg, cyan border, arrow icon

---

## SCREEN 2: CHAT IN ACTION

> **Purpose**: Conversational AI with tool execution display.
> **Figma frame**: 1440 x 900

### Same base layout as Screen 1, plus Chat History Popover

**Chat History Popover** (above command bar):
```
position: absolute; bottom: 48px; left: 10px;
width: 500px; max-height: 600px;
background: rgba(22, 22, 22, 0.95);
backdrop-filter: blur(20px);
border: 1px solid rgba(82, 82, 82, 0.3);
border-radius: 8px;
box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5);
animation: popover-slide-up 0.2s ease-out;
overflow-y: auto;
```

### Chat Messages (inside popover)

**User message** (right-aligned):
- Label: "YOU" — 9px, weight 700, uppercase, `#7c4dff`, text-align right
- Content bubble: `rgba(124, 77, 255, 0.12)` bg, `rgba(124, 77, 255, 0.15)` border, 4px radius, 8px 10px padding
- Text: "What's the grid connection cost for this 5MW site?" — 12px, `#f4f4f4`

**Tool call (running)** (left-aligned, inline):
```
border: 1px solid rgba(0, 229, 255, 0.2);
border-radius: 3px;
background: rgba(0, 0, 0, 0.2);
```
- Header row: gear icon (spinning, `#f1c21b` yellow) + "GRID_STUDY" (11px, weight 600, `rgba(15,98,254,0.6)`) + "Querying DNO headroom..." (11px, `#8d8d8d`)
- Spinner: `animation: chat-spin 1s linear infinite`

**Tool call (done)** (left-aligned, inline):
- Same container but border `rgba(82,82,82,0.2)` (not cyan)
- Icon: checkmark replaces gear (no animation)
- Expandable: click header to show/hide result
- Result panel: `rgba(0,0,0,0.15)` bg, 10px mono font, max-height 150px scroll

**Assistant message** (left-aligned):
- Label: "FEASIBLY" — 9px, weight 700, uppercase, `rgba(0,229,255,0.6)`
- Content bubble: `rgba(0, 229, 255, 0.05)` bg, `rgba(0, 229, 255, 0.08)` border
- Text: Multi-line response, 12px, `#f4f4f4`
- `strong` elements: `#0f62fe` color
- `code` elements: `rgba(0,0,0,0.3)` bg, 11px, 2px radius

**Map layer indicator** (inside message):
- Green dot (8px, `#4caf50`) + "solar_site_boundary added to map" — 11px, `#00e5ff`
- Container: `rgba(0,229,255,0.08)` bg, `rgba(0,229,255,0.12)` border, 3px radius

**Welcome state** (no messages):
- Title: "Feasibly AI" — 14px, weight 700, `#0f62fe`
- Sub: "Ask about solar yield, grid connections, energy pricing, or upload data for analysis." — 11px, `#8d8d8d`, line-height 1.5

---

## SCREEN 3: AGENT PANEL — Structured Analysis

> **Purpose**: Show structured GO/CAUTION/NO-GO verdict.
> **Figma frame**: 1440 x 900

### Right panel shows full Agent Verdict expanded (instead of floating cards)

**Intent Selector** (top, horizontal wrap):
- Pill buttons with colored borders, flex-wrap, gap 6px
- Colors per intent:
  - feasibility: `#4caf50` (green)
  - grid_study: `#2196f3` (blue)
  - financial: `#ff9800` (orange)
  - environmental: `#009688` (teal)
  - satellite: `#1565c0` (dark blue)
  - legacy: `#607d8b` (slate)
  - bess: `#00bcd4` (cyan)
- Active: filled bg, white text, 4px radius
- Inactive: transparent bg, colored border + text
- Font: 10px, weight 700, uppercase

**Run Agent Button**: `#0f62fe` bg, white text, "RUN AGENT", 10px weight 700

**Verdict Banner** (full-width):
- "GO" — 28px weight 800, white on `#4caf50` bg
- "87% conf" — 14px, `rgba(255,255,255,0.8)`
- "FEASIBILITY" — 9px, uppercase, `rgba(255,255,255,0.6)`

**Summary**: Paragraph, 13px, `#c6c6c6`, line-height 1.5

**Three Columns** (grid-template-columns: 1fr 1fr 1fr, gap: 16px):

**Risks** (red dot `#f44336` prefix):
1. "Cumulative landscape impact — 2 solar farms within 5km"
2. "ALC Grade 3b boundary — verify with soil survey"
3. "G99 application required for 5MW capacity"

**Opportunities** (green dot `#4caf50` prefix):
1. "12.5 MW headroom — expansion to 10MW possible"
2. "South-facing, <3 deg slope"
3. "No heritage assets within 500m"
4. "85% LPA solar approval rate"

**Next Steps** (blue dot `#0f62fe` prefix):
1. "Grid study with SSEN"
2. "Pre-planning enquiry"
3. "ALC soil survey"
4. "BNG baseline"

Dot: 6px circle, flex-shrink: 0
Text: 11px, `#c6c6c6`

**Suggested Actions** (bottom, flex row, gap 8px):
- 3 button cards with colored left-borders (3px):
  - "Run Grid Study" — blue `#2196f3` border
  - "Environmental Analysis" — teal `#009688` border
  - "Financial Model" — orange `#ff9800` border
- Each: glass bg, 4px radius, 10px padding, 11px weight 600

---

## SCREEN 4: SITE PICKER — Search Modal

> **Figma frame**: 1440 x 900

### Map dimmed in background

### Site Picker Modal (centered):
```
width: 380px;
background: rgba(22, 22, 22, 0.95);
backdrop-filter: blur(20px);
border: 1px solid rgba(82, 82, 82, 0.3);
border-radius: 12px;
box-shadow: 0 16px 64px rgba(0, 0, 0, 0.5);
padding: 24px;
animation: sp-pop-in 0.3s ease-out;
```

**Title**: "Select a site" — 16px, weight 800, `#f4f4f4`

**Tabs** (3, flex row, gap 0):
- `Search` | `Coordinates` | `Map Pin`
- Each tab: icon (14px) + label (11px, weight 600)
- Active: `rgba(15,98,254,0.15)` bg, `#0f62fe` text, `#0f62fe` bottom-border 2px
- Inactive: transparent, `#8d8d8d` text, `#525252` border

**Search Input**: full width, `#393939` bg, 13px mono, placeholder "Address, postcode, or place name..."
- Focus: `#0f62fe` border

**Suggestions** (below input):
- Glass bg, 6px radius, shadow
- Each item: `📍 Bicester, Oxfordshire` — 12px, hover `rgba(15,98,254,0.08)` bg
- Max 5 visible, scrollable

**Coordinates Tab**:
- Two inputs side by side: Lat (placeholder "52.4862") + Lon (placeholder "-1.8904")
- "Go to Site" button below, `#0f62fe` bg (disabled if empty)

**Map Pin Tab**:
- Pulsing dot animation
- Text: "Click anywhere on the map to select a site location" — 12px, `#c6c6c6`

---

## SCREEN 5: NOM EXPLORER — Grid Network Map

> **Figma frame**: 1440 x 900

### Three-column layout (no standard app header)

**Left Panel** (280px, `rgba(38,38,38,0.95)` bg):
- Header: `#003da5` blue bg, white text, "Network Opportunity Map" + sun icon
- Filters stack (vertical, gap 12px):
  - Map Type dropdown: "Primary — Generation"
  - View toggle: "Connected | Other" (Connected active in `#003da5`)
  - Supply Type: "All types"
  - Constraint: "All"
  - Licence Area: "SSEN"
  - Search: text input with search icon
- Result count: "847 substations" — count in `#0f62fe`, weight 700
- "BACK TO MAP" button: ghost style, bottom

**Center** (map, fills remaining):
- Lighter basemap (not dark — NOM uses standard Mapbox light)
- Hundreds of colored dots:
  - Green: headroom >= 10 MW
  - Amber: 3-10 MW
  - Red: < 3 MW
- Legend (bottom-left): Green "Available" | Amber "Constrained" | Red "Full"

**Right Panel** (340px):
- Substation name: "Bicester 33kV Primary" — 15px, weight 700
- Badges: "PRIMARY" cyan pill, "33kV" voltage badge
- **Headroom Grid** (2x2):
  - "Gen Headroom": "12.5 MW" (green RAG: `rgba(76,175,80,0.15)` bg + `#4caf50` text)
  - "Demand Headroom": "8.2 MW" (green)
  - "Gen Connected": "4.3 MW"
  - "Demand Connected": "15.7 MW"
- Info rows (key-value): Voltage, Licence Area, GSP, District
- "ANALYSE THIS SUBSTATION" button: `#003da5` bg, white text

---

## SCREEN 6: LAYOUT EDITOR — Plan Stage

> **Figma frame**: 1440 x 900

### Header: "PLAN" breadcrumb active (blue fill)

**Map with layout overlay**:
- Blue dashed site boundary
- Solar panel arrays: blue rectangles in rows
- Inverters: orange squares at row ends
- Battery: green rectangle
- Transformer: gray square
- Cable routes: dark dashed lines

**Component Palette** (left, 240px, glass bg):
```
position: absolute; top: 400px; left: 12px;
width: 240px; max-height: calc(100vh - 420px);
```
- Header: "COMPONENTS" — 11px, uppercase, `#0f62fe`
- Collapsible categories (chevron toggle):
  - **Panels** (blue dots): "Jinko Tiger Neo 580W — £0.18/W", "LONGi Hi-MO 6 — £0.17/W"
  - **Inverters** (orange dots): "Huawei SUN2000-100KTL — £4,200"
  - **Storage** (green dots): "BYD Battery-Box Premium — £5,800"
  - **Balance of System** (cyan dots)
- Each item: hover → grab cursor, blue glow border
- Drag-and-drop to map/3D editor

**Auto-BOM** (shown in InventoryCard):
- Total panels: 9,480
- Total capacity: 5.5 MW
- Estimated cost: £2.1M

---

## SCREEN 7: 3D DIGITAL TWIN

> **Figma frame**: 1440 x 900

### Full-screen overlay (z-index 1000)

**Toolbar** (top, 48px):
```
height: 48px;
background: rgba(22, 22, 22, 0.95);
backdrop-filter: blur(20px);
border-bottom: 1px solid rgba(82, 82, 82, 0.3);
```
- Close button (X, 32x32)
- "3D DIGITAL TWIN" — `#7c4dff` text, 11px weight 800
- Coordinates: XX.XXXXN, XX.XXXXX/E
- Time slider: 5-20h (0.5h step)
- Season toggles: `SUM` | `EQU` | `WIN`
- Layer toggles: `TERR` | `BLDG` | `SOLR` | `PATH` | `DETC` | `RETRO`
- Tool buttons: Measure (ruler), Screenshot

**3D Scene**:
- Terrain mesh: height-colored (brown valleys → green hills)
- Buildings: gray `#78909c`
- Solar panels: blue `#1e88e5`, 25° tilt, south-facing, with shadows
- Sun path arcs:
  - Summer: `#ffeb3b` yellow (high arc)
  - Equinox: `#ff9800` orange (medium)
  - Winter: `#2196f3` blue (low)
- Inverters: orange `#ff9800`
- Batteries: green `#4caf50`
- Transformers: gray `#9e9e9e`

**Info Panel** (bottom-right):
```
position: absolute; bottom: 16px; right: 16px;
width: 280px; padding: 12px 16px;
background: rgba(22, 22, 22, 0.9);
backdrop-filter: blur(20px);
border-radius: 8px;
```

**Measurement tool**: Cyan `#00e5ff` line between two points, "Distance: XX.Xm"

---

## SCREEN 8: SITE DASHBOARD

> **Figma frame**: 1440 x 900

### Full overlay (centered, max 1400px):
```
width: min(90vw, 1400px);
max-height: 90vh;
overflow-y: auto;
background: rgba(22, 22, 22, 0.95);
backdrop-filter: blur(24px);
border: 1px solid rgba(82, 82, 82, 0.3);
border-radius: 12px;
```

**Header**:
- "Site Assessment" — 16px, weight 800
- Coordinates, Parcel ID (12 chars)
- "Explore on Map" + "3D Twin" buttons

**3-Column Grid** (grid-template-columns: 1fr 2fr 1fr, gap: 16px):

**Left**: Radar chart (SVG, 200x200px)
- 8 axes: Solar, Grid, Terrain, Planning, Environmental, Financial, Land Use, Imagery
- Filled polygon, `#0f62fe` fill with opacity
- Score labels on each axis tip
- Overall score below: "82%" in 28px bold

**Center**:
- KPI row (3 cards): Grid Distance, Solar Yield, Verdict
- 9 domain cards (3x3 grid): Each shows icon + name + "Available"/"Pending" status

**Right**:
- Verdict card: Badge + summary + risks + opportunities
- AI Reports grid (2x3): Feasibility, Grid, Financial, Environmental, Satellite, Planning
- Quick Stats: Annual Energy, Site Score, Mean Slope, Planning Apps, Capacity

---

## SCREEN 9: SATELLITE ANALYSIS (GeeFlow Results)

> **Figma frame**: 1440 x 900

### Map with satellite imagery visible

**Floating Cards** (right, 380px):

**Land Use Card** (accent: `#1565c0`):
- Stacked bar chart of 9 DynamicWorld classes:
  - grass 62% (green), crops 18% (yellow), built 8% (red), trees 7% (blue), shrub 3%, bare 1%, water 0.5%
- "80% DEVELOPABLE" center text
- Legend with colored swatches

**Terrain Card** (accent: `#2196f3`):
- Elevation: 88m AOD (range 82-96m)
- Slope: mean 2.8° (p90: 5.1°, max: 8.3°)
- Aspect: 72% south-facing → "SSW"

**Solar Resource Card**:
- Annual GHI: 1,045 kWh/m²
- Monthly bars (12, `#ff9800`) with GHI values per month

**Vegetation Card**:
- Green cover: 69%
- Annual NDVI: 0.58
- Trend: "stable" (line chart)

**Flood Risk Card**:
- Risk Level: "LOW" — green badge (`#4caf50` bg)
- Water occurrence: 0.8%
- "No environmental constraint" — green text

---

## SCREEN 10: SITE PROSPECTOR

> **Figma frame**: 1440 x 900

### Map with 25 candidate markers

**Markers**: Numbered 1-25, colored by score:
- Green (>80): `#4caf50`
- Yellow (60-80): `#ff9800`
- Red (<60): `#f44336`
- #1 highlighted with pulse ring animation

**Right Panel** (380px):
- Header: "SITE PROSPECTOR" + "25 candidates scored"
- Tabs: `score` | `scan` | `similar`
- Controls: Technology (Solar/Wind/Battery), Region dropdown

**Results list** (scrollable):
- Each row: Rank # | Score bar (0-100, colored fill) | Location | Key metrics
  - #1: Score 92, "Greenfield, Bicester" — 1.8km grid, 10.9% CF
  - #2: Score 87, "Meadow Farm, Aylesbury" — 2.1km grid, 10.7% CF
  - #3: Score 84, "Long Crendon Fields" — 3.2km grid, 11.1% CF

**Radar Chart** (in detail view):
- 5 axes: Resource, Terrain, Land Use, Grid, Planning
- Filled polygon, `#0f62fe` fill
- Score labels on each axis

---

# PART 4: COMPLETE CARD COMPONENT REFERENCE

All 25 floating card types with full visual specification.

## Card Common Structure
```
Glass container: rgba(22, 22, 22, 0.85) bg, blur(12px), 8px radius
Border: 1px solid rgba(82, 82, 82, 0.3)
Padding: 12px
Shadow: 0 4px 24px rgba(0, 0, 0, 0.4)
Header: colored dot (8px) + title (11px, 800wt, UPPER) + collapse chevron
Sections separated by 1px border-top rgba(82,82,82,0.15)
```

### 1. ScoreCard — accent `#4caf50`
- Title: "SCORE"
- Badge: "XX/120" — colored by percentage (>70% green, >40% orange, <40% red)
- Score component chips: "name: value" badges
- Explanation: pre-formatted text block

### 2. SolarCard — accent `#ff9800`
- Title: "SOLAR"
- Hero: "XXXX kWh/yr" (14px, bold)
- CF: "XX.X% CF" (12px, orange)
- Monthly energy bars (12, green `#4caf50`)
- SAM 24h chart (day bars, orange/gray)
- ML prediction bars (purple `#9c27b0`)

### 3. TerrainCard — accent `#2196f3`
- Title: "TERRAIN"
- Slope stats: Mean, Min, Max
- Slope histogram (blue bars)
- 3D terrain viewer / Layout editor
- Imagery badge: "Flat terrain confirmed" or "Steep slope detected"

### 4. GridContextCard — accent `#00bcd4`
- Title: "GRID"
- 24h demand bars (cyan)
- Solar generation bars (orange)
- Curtailment risk bars (color by value)
- Weather strip: Temp, Cloud%, Solar W/m²
- Monthly solar bars (12, orange)
- Imagery badge: "HV line detected nearby"

### 5. PlanningCard — accent `#e91e63`
- Title: "PLANNING"
- Count: "X apps"
- Category chips with count badges
- Decision breakdown: Granted (green), Refused (red), Other (orange)
- Imagery badge: "Heritage features flagged"

### 6. VisionCard — accent `#7c4dff`
- Title: "VISION"
- Tabs: `instant` | `deep` | `upload`
- Instant: ScoreGauge (circle SVG), findings grid (2-col), usable area pie, domain badges
- Deep: "Run Deep Analysis" button, verdict badge
- Upload: ImageUploader component

### 7. SatelliteCard — accent `#1565c0`
- Title: "SATELLITE"
- Land use stacked bar (9 classes, colored)
- Terrain stats (elevation, slope, aspect)
- Solar resource monthly bars
- Vegetation (NDVI, green cover)
- Flood risk badge (HIGH red, MEDIUM orange, LOW green)
- SAR backscatter (VV/VH dB, soil moisture)
- NDVI timeseries (annual bars, trend)
- Score gauge with recommendation

### 8. PricingCard — accent `#7c4dff`
- Title: "PRICE & DEMAND"
- Demand forecast: Now MW, status (RED/AMBER/GREEN), 24h bars, 7-day bars
- Agile pricing: "Octopus Agile — region", Now p/kWh, heatmap grid (48 slots/day)
  - Slot colors: <10p green, 10-20p light green, 20-30p orange, >30p red
- Site revenue: Avg/Peak GBP/MWh, annual projections

### 9. StorageCard — accent `#00bcd4`
- Title: "STORAGE INTELLIGENCE"
- Battery arbitrage: Buy/Sell prices, spread, daily/annual revenue
- 24h price timeline bars (colored by price band)
- 2050 optimization: Optimal GW, adequacy %, cost, LCOE

### 10. BESSOptimizerCard — accent `#4caf50`
- Title: "BESS OPTIMIZER"
- Tabs: `score` | `sizing` | `revenue` | `colocation`
- MW slider (1-500), strategy dropdown
- Score (0-100), recommendation badge (HIGH_PRIORITY/PROMISING/MARGINAL/NO-GO)
- Financial: NPV, IRR, CAPEX, Payback, Annual revenue
- Colocation benefits cards (4)

### 11. GridEfficiencyCard — accent `#795548`
- Title: "GRID EFFICIENCY"
- Tabs: `losses` | `health`
- Controls: Distance km, Voltage kV (11-400), Load MW
- Loss % colored: >3% red, >1.5% orange, ≤1.5% green
- Loss MW, loading ratio, annual cost

### 12. NGEDOpportunityCard — accent `#1b5e20`
- Title: "NGED NETWORK"
- Count: "XX substations"
- RAG breakdown: Green >5MW, Amber 1-5MW, Red <1MW
- Regional table: Region | Subs | Matched% | Headroom MW
- Top opportunities: Substation | Region | MVA | Headroom (colored)

### 13. StabilityCard — accent dynamic (green/orange/red by risk)
- Title: "GRID STABILITY (DSGC)"
- 6 sliders: Reaction time, Price elasticity, Demand scale, Renewable %, EV load, Battery storage
- Stable/Unstable node counts (green/red)
- Cascade risk: LOW/MODERATE/HIGH/CRITICAL (uppercase, colored)
- Most vulnerable nodes list (top 6)

### 14. EnergyAnalyticsCard — sub-components:
- **SolarForecastChart**: 96-interval bars + irradiation dots
- **Thermograph**: Hour × Day heatmap (blue→yellow→red)
- **StabilityGauge**: Radial gauge (0°→180°), risk zones
- **ProsumerChart**: Dual bar (green production, red consumption)
- **TurbineThermograph**: Component × fault temperature matrix
- **TransmissionStatus**: Line status with phase indicators (Va, Vb, Vc)

### 15. DeferralCard — accent `#607d8b`
- Title: "DEFERRAL"
- Load/Gen MW inputs + Run button
- Table: Node | Capacity (MVA) | Load kW | Gen kW

### 16. EnergySystemCard — accent `#795548`
- Title: "2050 SYSTEM"
- Annual generation: XXXk MWh/yr
- CF, Homes powered, CO2 avoided
- Solar/System LCOE comparison
- Renewable capacity GW, demand TWh, total cost

### 17. InventoryCard — accent `#e65100`
- Title: "BOM"
- Custom layout count: "X placed, Y types"
- Panel/Inverter counts
- Total cost, Cost/kW
- Supply chain: fulfilment %, nearest km
- BOM item rows: name, qty, unit, cost

### 18. ProcurementCard — accent `#ff5722`
- Title: "PROCUREMENT INTELLIGENCE"
- Tabs: `pipeline` | `benchmarks`
- Active tenders count, urgent (<14d), total value
- Benchmarks table: Technology | Min/Median/Max £

### 19. TendersCard — accent `#ff9800`
- Title: "ENERGY TENDERS"
- Source badges: Find a Tender (`#1565c0`), Sell2Wales (`#c62828`), Contracts Finder (`#2e7d32`)
- Deadline urgency: ⚡ if <7d (red), normal (orange)
- Value: £XXX (green)
- View → link (blue `#64b5f6`)

### 20. SiteProspectorCard — accent `#009688`
- Title: "SITE PROSPECTOR"
- Tabs: `score` | `scan` | `similar`
- Technology selector: Solar/Wind/Battery
- Score (0-100), recommendation badge
- Scan results: total, high priority, promising, top sites
- Similar: candidates within radius, similarity %

### 21. LegacyAssetCard
- Title: "LEGACY ASSET PLANNING & COMPLIANCE"
- Tabs: `assets` | `lifecycle` | `compliance` | `geoai`
- Asset types: Solar Farm, Wind Farm, Battery Storage, Substation
- Status: OPERATIONAL (green), DEGRADED (orange), END_OF_LIFE (red)
- Lifecycle: age, remaining years, output %, condition /100, progress bar
- Repowering: new capacity, gain %, cost, ROI years
- Compliance: framework status dots (G99, CDM, BNG, EIA)

### 22. LandClassifierCard — accent `#ff6f00`
- Title: "LAND CLASSIFIER"
- Tabs: `classify` | `retrofit` | `forecast`
- Class distribution stacked bars (colored by class)
- Retrofit score (0-100), technology scores
- Forecast grid by year with confidence %

### 23. HomeRetrofitCard — accent `#8e24aa`
- Title: "HOME RETROFIT"
- Tabs: `input` | `results` | `precedents`
- House type selector (12 types: Victorian Mid-Terrace through Modern New-Build)
- EPC ratings A-G (color-coded: A=#00c853 → G=#d50000)
- Planning badges: No Planning (green), PD (blue), Prior Approval (orange), Full Planning (pink), Listed (red)
- Energy saving progress bar (gradient purple→green)

### 24. RetrofitCard — accent `#607d8b`
- Title: "INFRASTRUCTURE RETROFIT & ENERGY STORAGE"
- Tabs: `assessment` | `storage` | `disruption` | `circularity`
- Infrastructure types: Hydropower Dam, Coal Plant, etc. (10)
- Storage tech: Pumped Hydro, CAES, Li-ion BESS, etc. (8)
- Verdict badge, score breakdown bars
- Cost comparison: Retrofit vs Greenfield saving
- Circularity score, material reuse %, EU Taxonomy alignment

### 25. AgileSlotGrid (sub-component)
- 48 half-hour slots per day heatmap
- Colors: <10p green "cheap", 10-20p "moderate", 20-30p "expensive" orange, >30p "peak" red
- Current slot highlighted
- Tooltip: "YYYY-MM-DD HH:MM — XXp/kWh"

---

# PART 5: WORKFLOW STAGES & UI STATE CHANGES

## Stage Transitions

| Stage | Header State | Map State | Right Panel | Left Panel | Command Bar |
|-------|-------------|-----------|-------------|------------|-------------|
| **SITE** | No breadcrumbs, no sub-nav | Pick mode, hillshade only | None (empty) | None | "Search for a site..." |
| **STUDY** | Breadcrumbs + 7 sub-nav | Full layers, AI banners | AgentVerdict + intent cards | Layer Rail | "Ask about feasibility..." |
| **PLAN** | Breadcrumbs (PLAN active) | Layout overlay + drag-drop | Planning, Inventory, Energy, Deferral | Component Palette + Layer Rail | "Plan layout..." |
| **ACT** | Breadcrumbs (ACT active) | Standard layers | Legacy, Procurement, Tenders, Prospector | Layer Rail | "Export, tender..." |

## Study Sub-Step Card Mapping

| Sub-Step | Cards Shown (in order) |
|----------|----------------------|
| Feasibility | ScoreCard, SolarCard, TerrainCard, GridContextCard, PlanningCard, VisionCard |
| Grid Study | GridContextCard, GridEfficiencyCard, NGEDOpportunityCard, StabilityCard |
| Financial | PricingCard, DeferralCard, StorageCard, BESSOptimizerCard, EnergyAnalyticsCard |
| Environmental | SatelliteCard, LandClassifierCard, PlanningCard, TerrainCard, VisionCard |
| Satellite | SatelliteCard, LandClassifierCard, TerrainCard, VisionCard |
| Legacy | LegacyAssetCard, ProcurementCard, InventoryCard |
| BESS | BESSOptimizerCard, StorageCard, GridContextCard, PricingCard |

---

# PART 6: PRODUCTION NOTES FOR FIGMA

1. **Frame size**: All screens at 1440 x 900 (16:9)
2. **Export**: 2x resolution for retina (2880 x 1800)
3. **Font**: IBM Plex Mono from Google Fonts — monospace is ESSENTIAL to brand identity
4. **Everything monospace**: No sans-serif or serif anywhere. This conveys technical precision.
5. **Dark theme only**: No light mode exists or is planned
6. **Glass effect**: Figma background blur (12-20px) + semi-transparent fills
7. **Glow effects**: Verdict badges and status dots have colored box-shadow glows
8. **Corners**: 2px for buttons, 3-4px for inputs, 6-8px for cards, 12px for modals. Never round beyond 12px.
9. **Letter-spacing**: All uppercase text uses 0.5-4px letter-spacing (see typography table)
10. **Metric color consistency**: Each metric type has ONE color across all views (yield=orange, CF=cyan, score=green, grid=blue, confidence=purple)
11. **Left-border accents**: Many cards use a 3px colored left border to indicate their category
12. **Charts are inline SVG**: Bars, donuts, radar charts, histograms — all rendered inside cards as simple SVG shapes
13. **Scrollbar styling**: 4px width, transparent track, `rgba(82,82,82,0.3)` thumb, 2px radius
14. **No icons library**: All icons are inline SVG paths (Heroicons-style, 16-20px)
15. **Hover states**: buttons get border-color change + color change, never background-color-only changes
16. **Transitions**: All interactive elements use `transition: all 0.15s` for smooth state changes
