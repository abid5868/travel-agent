# FINAL ITINERARY

## Wedding Weekend Portland — Family of 6 | Sept 10–13, 2026

> **⚠️ DYNAMIC EVENT RESOLVED:** Hotel double-booking cascade handled — see **Accommodation Replan** section below.

---

## PARTY OVERVIEW

| Traveler | Type | Special Needs |
|---|---|---|
| Adult 1 | Adult | — |
| Adult 2 | Adult | — |
| Adult 3 | Adult | — |
| Adult 4 | Adult | — |
| Teen 1 | Teen | — |
| Elder 1 | Elderly | Wheelchair-dependent, mobility assistance required |

---

## 🏨 ACCOMMODATION REPLAN — Double-Booking Resolution

### What Happened
The originally booked hotel (Pearl District Accessible Boutique Hotel, `hotel_PDX_001`) contacted us with an urgent double-booking error. Their only remaining accessible room accommodates a maximum of 3 people, which is insufficient for a party of 6 requiring full wheelchair accessibility throughout.

### Decision Analysis

| Option | Feasibility | Accessibility | Notes |
|---|---|---|---|
| Option 1: One accessible + non-accessible overflow | ❌ Rejected | Fails mandatory constraint | Non-accessible rooms violate `wheelchair_accessible_mandatory` |
| Option 2: Split across two hotels | ⚠️ Partial | Requires verification | `hotel_PDX_003` is **NOT wheelchair accessible** — eliminated |
| Option 3: Airbnb + hotel mix | ❌ Rejected | Unverifiable accessibility | Not in inventory; cannot guarantee ADA compliance |

### ✅ CHOSEN SOLUTION: Consolidate at Oregon Convention Center Hotel (`hotel_PDX_002`)

**Rationale:**
- `hotel_PDX_002` has a **family_suite (capacity 6, $359/night)** — the entire party under one roof
- Fully wheelchair accessible: roll-in shower, grab bars, elevator, accessible parking, TTY phones
- Light rail access for event transportation
- All mandatory event venues accessible via the booked accessible van
- Keeps the group **coherent** — no splitting required
- Brings the elderly member's room within the same suite — no cross-hotel transfers needed
- `hotel_PDX_001` has been notified; `hotel_PDX_002` confirmed for 3 nights

**Room Assignment — `hotel_PDX_002`, Family Suite (capacity 6):**
- Elder 1 assigned to the accessible wing of the family suite (roll-in shower, grab bars)
- Adults 1–4 and Teen 1 in remaining suite beds
- All bathroom accessibility features preserved within one suite

---

## ✈️ FLIGHTS

### Outbound — Thursday, September 10, 2026

| Detail | Info |
|---|---|
| **Flight ID** | `flight_SEA_POR_001` |
| **Airline/Number** | Horizon Express HE501 |
| **Route** | Seattle (SEA) → Portland (PDX) |
| **Departure** | 08:00 |
| **Arrival** | 09:15 (avg +8 min delay → ~09:23) |
| **Aircraft** | Airbus A319 |
| **Stops** | 0 (direct) |
| **Wheelchair Accessible** | ✅ Yes |
| **Seats** | 6 |
| **Price per seat** | $109 |
| **Baggage fee** | $35 × 6 bags |
| **Days Available** | Includes Thursday ✅ |

> **Note:** September 10, 2026 is a **Thursday** — confirmed available day for HE501.

### Return — Sunday, September 13, 2026

| Detail | Info |
|---|---|
| **Flight ID** | `flight_POR_SEA_001` |
| **Airline/Number** | Pacific Air PA302 |
| **Route** | Portland (PDX) → Seattle (SEA) |
| **Departure** | 18:00 |
| **Arrival** | 19:15 (avg +17 min → ~19:32) |
| **Aircraft** | Airbus A319 |
| **Stops** | 0 (direct) |
| **Wheelchair Accessible** | ✅ Yes |
| **Seats** | 6 |
| **Price per seat** | $109 |
| **Baggage fee** | $25 × 6 bags |
| **Days Available** | Includes Sunday ✅ |

---

## 🚐 GROUND TRANSPORTATION

### Portland Mobility-Plus Full-Size Van Rental
**Activity ID:** `act_PDX_transport_001`

| Detail | Info |
|---|---|
| **Type** | Accessible van with hydraulic wheelchair lift + Q'Straint tie-down |
| **Capacity** | 7 (fits all 6 travelers + luggage) |
| **Wheelchair Accessible** | ✅ Yes |
| **Price** | $25/person/day × 6 persons × 3 days |
| **Booking Required** | Yes — booked 1+ day in advance ✅ |
| **Pickup** | 700 SW Taylor St, Portland (Downtown) |
| **Coverage** | All 3 days: Thursday arrival through Sunday departure |

> The van is the **primary transport** for all mandatory events (rehearsal dinner, ceremony, family brunch) and optional activities. It ensures the elderly wheelchair-dependent member can be transported door-to-door for every venue.

---

## 📅 DAY-BY-DAY ITINERARY

---

### DAY 1 — Thursday, September 10, 2026 (Travel Day)

**Theme: Arrive & Settle In**

| Time | Activity | Details |
|---|---|---|
| 06:30 | Depart for Seattle Airport | Allow extra time for wheelchair boarding assistance |
| 08:00 | **Flight HE501 departs** SEA | Horizon Express, wheelchair accessible, board early |
| 09:23 | **Arrive Portland PDX** | (~09:15 scheduled + 8 min avg delay) |
| 09:30–10:15 | Airport accessible services | Wheelchair assistance, baggage claim, accessible restrooms |
| 10:15 | **Pick up Mobility-Plus Van** | `act_PDX_transport_001` — 700 SW Taylor St; arrange airport pickup via rental shuttle |
| 10:45 | **Check-in: Oregon Convention Center Hotel** | `hotel_PDX_002`, 1000 NE Multnomah St — Family Suite (6 guests) |
| 11:00–12:30 | Settle in, unpack, review room accessibility | Confirm roll-in shower, grab bars operational for Elder 1 |
| 12:30–14:00 | **Lunch at Rose City Downtown Grill** | `rest_122` — accessible, group of 6 ✅, $38/pp, kid menu available |
| 14:00–16:00 | **Portland Art Museum** | `act_PDX_004` — ADA accessible, elevators, wide galleries; $25/pp |
| 16:00–17:00 | Return to hotel, rest | Elder 1 rest period before evening |
| 17:30 | **Dinner at Willamette Riverfront Bistro** | `rest_117` — accessible, kid menu, scenic waterfront view; $45/pp |
| 19:30 | Return to hotel | Early night ahead of busy Friday |

---

### DAY 2 — Friday, September 11, 2026 (Rehearsal Day)

**Theme: Wedding Rehearsal & Rehearsal Dinner**

| Time | Activity | Details |
|---|---|---|
| 08:00–09:30 | **Breakfast at hotel restaurant** | `hotel_PDX_002` has on-site restaurant; accessible |
| 09:30–11:30 | **Powell's City of Books Guided Tour** | `act_PDX_003` — FREE, wheelchair accessible, elevator, Pearl District; 1.5 hrs |
| 11:30–13:00 | **Lunch at Rose City Downtown Grill** | `rest_122` — accessible, group of 6 ✅, $38/pp |
| 13:00–15:00 | Afternoon rest / wedding preparation | Elder 1 rest; others prep for rehearsal |
| 15:00–17:30 | **Wedding Rehearsal at Pittock Mansion** | `act_PDX_001` — ADA-accessible terrace & interior; drive via Mobility-Plus Van (~15 min from Lloyd District) |
| 17:30–18:00 | Travel to rehearsal dinner | Mobility-Plus Van to Pearl District (~10 min) |
| **18:00** | ⭐ **REHEARSAL DINNER — Pearl District Grand Atrium** | `rest_116` — **Mandatory Friday 6pm event** ✅; accessible, group up to 20, universal design; $40/pp |
| 20:30–21:00 | Return to hotel | Mobility-Plus Van |
| 21:00 | Early rest | Big day tomorrow |

> ✅ **Mandatory Event Confirmed:** Rehearsal Dinner at Pearl District Grand Atrium, Friday 18:00 — wheelchair accessible, universal design features, seats up to 20.

---

### DAY 3 — Saturday, September 12, 2026 (Wedding Day)

**Theme: The Wedding Ceremony**

| Time | Activity | Details |
|---|---|---|
| 08:00–09:30 | **Breakfast at Universal Design Brunch Hall** | `rest_119` — Opens 07:30 Sat ✅; accessible, group up to 25, $30/pp |
| 09:30–11:30 | **Portland Japanese Garden** | `act_PDX_002` — ADA-accessible paths, wheelchair friendly; $20/pp; peaceful pre-wedding family time |
| 11:30–12:30 | Return to hotel, dress for ceremony | Allow extra time for Elder 1 |
| 12:30 | Depart for Pittock Mansion | Mobility-Plus Van — allow 20–25 min from Lloyd District |
| 13:00 | Arrive Pittock Mansion early | `act_PDX_001` — confirm accessible entrance and seating for Elder 1 |
| **14:00–18:00** | ⭐ **WEDDING CEREMONY — Pittock Mansion** | `act_PDX_001` — **Mandatory Saturday 2pm event** ✅; ADA outdoor terrace + interior; fully wheelchair accessible; $120/pp; 4 hours |
| 18:00–18:30 | Post-ceremony photos, transition | Remain on accessible terrace |
| 18:30 | Depart to dinner | Mobility-Plus Van |
| 19:00–21:30 | **Wedding Reception/Evening Dinner** at Southeast Garden Pavilion | `rest_121` — accessible, outdoor seating, group up to 10 ✅; $60/pp |
| 21:30 | Return to hotel | |

> ✅ **Mandatory Event Confirmed:** Wedding Ceremony at Pittock Mansion, Saturday 14:00 — fully ADA accessible outdoor terrace, elevator access, accommodates 150 guests.

---

### DAY 4 — Sunday, September 13, 2026 (Departure Day)

**Theme: Family Brunch & Fly Home**

| Time | Activity | Details |
|---|---|---|
| 07:30 | Wake, prepare | Allow extra time for Elder 1 morning routine |
| **09:00–11:00** | ⭐ **FAMILY BRUNCH — Universal Design Brunch Hall** | `rest_119` — **Mandatory Sunday 9am event** ✅; opens 07:30 Sun ✅; wheelchair accessible, group up to 25, $30/pp; vegetarian & kid menu available |
| 11:00–12:00 | Return to hotel, check out | Mobility-Plus Van |
| 12:00–14:00 | **Portland Aerial Tram Scenic Ride** *(optional)* | `act_PDX_005` — roll-on/roll-off accessible for wheelchairs; $8/pp; 1 hour; operate until 17:00 Sat — NOTE: Check Sunday hours; listed days include Saturday but not Sunday. **Skip if unavailable** → replace with hotel lobby rest |
| 14:00–15:30 | Return van rental / transfer to PDX Airport | Allow ample transfer time |
| 15:30 | Arrive Portland Airport, check-in, wheelchair assistance | PDX Terminal accessible services |
| 16:00–17:30 | **PDX Terminal Quick-Service** (optional snack/early dinner) | `rest_120` — accessible, $18/pp; airport-side convenience |
| **18:00** | **Flight PA302 departs** PDX | Pacific Air, wheelchair accessible |
| 19:32 | **Arrive Seattle** (~19:15 + 17 min delay) | Home ✅ |

> ✅ **Mandatory Event Confirmed:** Family Brunch at Universal Design Brunch Hall, Sunday 09:00 — wheelchair accessible, seats up to 25, brunch menu, kid-friendly.

> ⚠️ **Aerial Tram Note:** `act_PDX_005` is listed for Monday–Saturday only. Sunday availability is not confirmed in inventory. This activity is marked optional and can be skipped without impacting mandatory events or budget.

---

## 💰 FULL BUDGET BREAKDOWN

### Flights

| Item | Calc | Cost |
|---|---|---|
| Outbound HE501 — seats × 6 | $109 × 6 | $654 |
| Outbound baggage fees | $35 × 6 | $210 |
| Return PA302 — seats × 6 | $109 × 6 | $654 |
| Return baggage fees | $25 × 6 | $150 |
| **Flights Subtotal** | | **$1,668** |

### Accommodation

| Item | Calc | Cost |
|---|---|---|
| `hotel_PDX_002` Family Suite × 3 nights | $359 × 3 | $1,077 |
| **Accommodation Subtotal** | | **$1,077** |

### Ground Transportation

| Item | Calc | Cost |
|---|---|---|
| Mobility-Plus Van | $25/pp × 6 × 3 days | $450 |
| **Transportation Subtotal** | | **$450** |

### Activities

| Activity | Calc | Cost |
|---|---|---|
| Wedding Ceremony `act_PDX_001` | $120 × 6 | $720 |
| Portland Japanese Garden `act_PDX_002` | $20 × 6 | $120 |
| Powell's Books Tour `act_PDX_003` | FREE | $0 |
| Portland Art Museum `act_PDX_004` | $25 × 6 | $150 |
| Portland Aerial Tram `act_PDX_005` *(optional)* | $8 × 6 | $48 |
| **Activities Subtotal** | | **$1,038** |

### Restaurants

| Meal | Restaurant | Calc | Cost |
|---|---|---|---|
| Thu Lunch | Rose City Downtown Grill `rest_122` | $38 × 6 | $228 |
| Thu Dinner | Willamette Riverfront Bistro `rest_117` | $45 × 6 | $270 |
| Fri Lunch | Rose City Downtown Grill `rest_122` | $38 × 6 | $228 |
| Fri Dinner (Rehearsal) | Pearl District Grand Atrium `rest_116` | $40 × 6 | $240 |
| Sat Breakfast | Universal Design Brunch Hall `rest_119` | $30 × 6 | $180 |
| Sat Reception Dinner | Southeast Garden Pavilion `rest_121` | $60 × 6 | $360 |
| Sun Brunch (Mandatory) | Universal Design Brunch Hall `rest_119` | $30 × 6 | $180 |
| Sun Airport (optional) | PDX Terminal Quick-Service `rest_120` | $18 × 6 | $108 |
| **Restaurants Subtotal** | | **$1,794** |

---

### 📊 GRAND TOTAL BUDGET SUMMARY

| Category | Cost |
|---|---|
| Flights | $1,668 |