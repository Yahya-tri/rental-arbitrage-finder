import streamlit as st
import pandas as pd
import numpy as np
import requests
from urllib.parse import quote_plus

st.set_page_config(page_title="Rental Arbitrage Finder", page_icon="🏠", layout="wide")

DAYS = 30.4

CITY_INFO = {
    "Washington, DC": {
        "city": "Washington", "state": "DC", "adr": 239, "occ": 0.57,
        "annual_revenue": 23700,
        "legal_note": "DC STR rules are restrictive. Do not sign a lease for arbitrage until the exact licensing, primary-residence, zoning, and building requirements are confirmed."
    },
    "Silver Spring, MD": {
        "city": "Silver Spring", "state": "MD", "adr": 125, "occ": 0.60,
        "annual_revenue": 12200,
        "legal_note": "Verify Montgomery County STR licensing, zoning, taxes, and lease/building rules before operating."
    },
    "Baltimore, MD": {
        "city": "Baltimore", "state": "MD", "adr": 142, "occ": 0.57,
        "annual_revenue": 15500,
        "legal_note": "Verify Baltimore City STR licensing, zoning, taxes, and lease/building rules before operating."
    },
}

st.title("🏠 Rental Arbitrage Finder")
st.caption("DMV-focused deal screening — find listings, rank the money, then work through the verification queue before contacting landlords.")

# -----------------------------
# Session state
# -----------------------------
for key, default in {
    "live_listings": pd.DataFrame(),
    "manual_properties": [],
    "research_notes": {},
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# -----------------------------
# Sidebar criteria
# -----------------------------
with st.sidebar:
    st.header("🎯 Your criteria")
    city = st.selectbox("Target market", list(CITY_INFO.keys()))
    max_rent = st.number_input("Maximum monthly rent", 500, 10000, 2500, 50)
    target_profit = st.number_input("Target monthly profit", 0, 10000, 1000, 100)
    minimum_score = st.slider("Minimum deal score", 0, 100, 70)
    bedrooms_min = st.number_input("Minimum bedrooms", 0, 10, 2, 1)
    bedrooms_max = st.number_input("Maximum bedrooms", int(bedrooms_min), 10, max(4, int(bedrooms_min)), 1)
    days_old = st.number_input("Only listings this many days old", 1, 180, 30, 1)
    property_types = st.multiselect(
        "Property types",
        ["Single Family", "Condo", "Townhouse", "Apartment", "Multi-Family"],
        default=["Single Family", "Condo", "Townhouse", "Apartment"],
    )

    st.header("💸 Operating costs")
    platform_fee = st.slider("Platform fee", 0.0, 0.20, 0.03, 0.005)
    utilities = st.number_input("Utilities + internet / month", 0, 1500, 250, 25)
    insurance = st.number_input("Insurance / month", 0, 500, 75, 10)
    supplies = st.number_input("Supplies / month", 0, 500, 100, 10)
    maintenance = st.number_input("Maintenance reserve / month", 0, 1000, 100, 10)
    other = st.number_input("Other fixed costs / month", 0, 2000, 100, 25)
    furnishing = st.number_input("Furnishing / setup cash", 0, 30000, 5000, 250)

    st.header("🧠 Screening rules")
    require_permission = st.checkbox("Require landlord/STR permission before SHORTLIST", value=True)
    require_bathrooms = st.checkbox("Flag low bathroom count", value=True)

info = CITY_INFO[city]

# -----------------------------
# Market snapshot
# -----------------------------
st.subheader("📊 DMV starter market benchmarks")
bench = pd.DataFrame([
    ["Washington, DC", 239, 0.57, 23700, "High demand; STR rules are restrictive"],
    ["Silver Spring, MD", 125, 0.60, 12200, "County rules/licensing must be checked"],
    ["Baltimore, MD", 142, 0.57, 15500, "Useful comparison market"],
], columns=["Market", "ADR", "Occupancy", "Annual Revenue", "Note"])
show = bench.copy()
show["ADR"] = show["ADR"].map(lambda x: f"${x:,.0f}")
show["Occupancy"] = show["Occupancy"].map(lambda x: f"{x:.0%}")
show["Annual Revenue"] = show["Annual Revenue"].map(lambda x: f"${x:,.0f}")
st.dataframe(show, use_container_width=True, hide_index=True)

# -----------------------------
# Helpers
# -----------------------------
def safe_float(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def make_search_url(query):
    return "https://www.google.com/search?q=" + quote_plus(query)


def research_links(address):
    q = address.strip()
    return {
        "Google": make_search_url(f'"{q}" rental'),
        "Zillow": make_search_url(f'"{q}" site:zillow.com'),
        "Realtor": make_search_url(f'"{q}" site:realtor.com'),
        "Apartments": make_search_url(f'"{q}" site:apartments.com'),
        "Airbnb comps": make_search_url(f'Airbnb {q} nearby'),
        "STR rules": make_search_url(f'{info["city"]} {info["state"]} short term rental rules'),
    }


def estimate_live_row(x):
    rent = safe_float(x.get("price", x.get("rent", 0)))
    beds = safe_float(x.get("bedrooms", 0))
    baths = safe_float(x.get("bathrooms", 0))
    bed_multiplier = {0: 0.65, 1: 0.78, 2: 0.92, 3: 1.15, 4: 1.35}.get(int(beds), 1.50)
    estimated_adr = info["adr"] * bed_multiplier
    estimated_occ = min(0.80, info["occ"] + max(0, beds - 2) * 0.02)
    bookings = max(1, round(estimated_occ * DAYS / 3.5))
    cleaning_fee = 100
    cleaning_cost = 60
    gross = estimated_adr * DAYS * estimated_occ + cleaning_fee * bookings
    platform = gross * platform_fee
    fixed = rent + utilities + insurance + supplies + maintenance + other
    cleaning = cleaning_cost * bookings
    net = gross - platform - cleaning - fixed
    contribution = estimated_adr * (1 - platform_fee)
    breakeven = np.nan
    if contribution > 0:
        breakeven = max(0, (fixed + cleaning - cleaning_fee * bookings * (1 - platform_fee)) / (DAYS * contribution))
    profit_score = np.clip((net / max(target_profit, 1)) * 40, 0, 40)
    margin_score = np.clip((net / max(gross, 1)) * 25, 0, 25)
    cushion_score = 0 if np.isnan(breakeven) else np.clip((estimated_occ - breakeven) * 50, 0, 20)
    rent_score = 15 if rent <= max_rent else 0
    score = int(round(min(100, profit_score + margin_score + cushion_score + rent_score)))
    address = x.get("formattedAddress") or x.get("addressLine1") or "Address unavailable"
    direct_url = x.get("listingUrl") or x.get("url") or x.get("website") or make_search_url(address + " rental")
    return {
        "Property": address,
        "Address": address,
        "Rent": rent,
        "Beds": beds,
        "Baths": baths,
        "ADR": estimated_adr,
        "Occupancy": estimated_occ,
        "Bookings": bookings,
        "CleaningFee": cleaning_fee,
        "CleaningCost": cleaning_cost,
        "Permission": "Unknown",
        "Property Type": x.get("propertyType", ""),
        "Days on Market": x.get("daysOnMarket", ""),
        "Listing": direct_url,
        "Gross Revenue": gross,
        "Monthly Net": net,
        "Annual Net": net * 12,
        "Break-even Occupancy": breakeven,
        "Startup Cash": rent + furnishing,
        "Deal Score": score,
        "Source": "RentCast",
    }


def calc_row(r):
    rent = safe_float(r.Rent)
    adr = safe_float(r.ADR)
    occ = min(max(safe_float(r.Occupancy), 0), 1)
    bookings = safe_float(r.Bookings)
    gross = adr * DAYS * occ + safe_float(r.CleaningFee) * bookings
    platform = gross * platform_fee
    cleaning = safe_float(r.CleaningCost) * bookings
    fixed = rent + utilities + insurance + supplies + maintenance + other
    net = gross - platform - cleaning - fixed
    contribution = adr * (1 - platform_fee)
    breakeven = np.nan
    if contribution > 0:
        breakeven = max(0, (fixed + cleaning - safe_float(r.CleaningFee) * bookings * (1 - platform_fee)) / (DAYS * contribution))
    profit_score = np.clip((net / max(target_profit, 1)) * 40, 0, 40)
    margin_score = np.clip((net / max(gross, 1)) * 25, 0, 25)
    cushion_score = 0 if np.isnan(breakeven) else np.clip((occ - breakeven) * 50, 0, 20)
    rent_score = 15 if rent <= max_rent else 0
    score = min(100, int(round(profit_score + margin_score + cushion_score + rent_score)))
    return pd.Series({
        "Gross Revenue": gross,
        "Monthly Net": net,
        "Annual Net": net * 12,
        "Break-even Occupancy": breakeven,
        "Startup Cash": rent + furnishing,
        "Deal Score": score,
    })


def action_for(row):
    rent_ok = row.Rent <= max_rent
    profit_ok = row["Monthly Net"] >= target_profit
    score_ok = row["Deal Score"] >= minimum_score
    permission = str(row.get("Permission", "Unknown"))
    bath_ok = not require_bathrooms or safe_float(row.Baths) >= 1
    if permission == "No":
        return "🔴 BLOCKED — STR permission denied"
    if require_permission and permission != "Yes":
        if rent_ok and profit_ok and score_ok and bath_ok:
            return "🟡 VERIFY — financially strong, permission unknown"
        return "🟡 VERIFY — needs owner/lease check"
    if rent_ok and profit_ok and score_ok and bath_ok:
        return "🟢 SHORTLIST — contact"
    if row["Monthly Net"] > 0:
        return "🟡 MAYBE — below target"
    return "🔴 PASS — negative net"

# -----------------------------
# Live RentCast search
# -----------------------------
st.divider()
st.subheader(f"🌐 Find live rental listings in {city}")
st.write("Pull active long-term listings, score them, and put the best ones into a verification/contact queue.")

with st.expander("🔑 Connect live listing search", expanded=False):
    api_key = st.text_input("RentCast API key", type="password", help="Used only for this Streamlit session. Never commit the key to GitHub.")
    st.caption("The key stays in the session. If RentCast says your subscription is inactive, the key itself may be valid but the API plan is not active.")

search_clicked = st.button("🔎 Find & rank rental listings", type="primary", use_container_width=True)

if search_clicked:
    if not api_key.strip():
        st.warning("Enter your RentCast API key first.")
    else:
        params = {
            "city": info["city"],
            "state": info["state"],
            "price": f"*:{int(max_rent)}",
            "bedrooms": f"{int(bedrooms_min)}:{int(bedrooms_max)}",
            "daysOld": f"*:{int(days_old)}",
            "limit": 50,
        }
        if property_types:
            params["propertyType"] = "|".join(property_types)
        try:
            response = requests.get(
                "https://api.rentcast.io/v1/listings/rental/long-term",
                params=params,
                headers={"Accept": "application/json", "X-Api-Key": api_key.strip()},
                timeout=20,
            )
            if response.status_code in (401, 403):
                st.error(f"RentCast rejected the request (HTTP {response.status_code}). Check the API key and that the RentCast subscription/API access is active.")
            elif not response.ok:
                st.error(f"RentCast returned HTTP {response.status_code}: {response.text[:500]}")
            else:
                payload = response.json()
                records = payload if isinstance(payload, list) else payload.get("listings", payload.get("data", []))
                rows = [estimate_live_row(x) for x in records]
                st.session_state.live_listings = pd.DataFrame(rows)
                st.success(f"Found {len(rows)} rental listings matching your filters.")
        except requests.RequestException as exc:
            st.error(f"Could not reach RentCast: {exc}")

if not st.session_state.live_listings.empty:
    live = st.session_state.live_listings.copy()
    live["Action"] = live.apply(action_for, axis=1)
    live = live.sort_values(["Deal Score", "Monthly Net"], ascending=False).reset_index(drop=True)

    st.subheader("🔥 Live listings ranked by estimated arbitrage potential")
    top = live.head(5)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Listings found", len(live))
    m2.metric("Financially promising", int(((live["Monthly Net"] >= target_profit) & (live["Deal Score"] >= minimum_score)).sum()))
    m3.metric("Need permission", int((live["Permission"] != "Yes").sum()))
    m4.metric("Best projected net", f"${live.iloc[0]['Monthly Net']:,.0f}" if len(live) else "$0")

    display_cols = ["Property", "Rent", "Beds", "Baths", "ADR", "Occupancy", "Gross Revenue", "Monthly Net", "Annual Net", "Startup Cash", "Deal Score", "Action", "Property Type", "Days on Market", "Listing"]
    live_display = live[display_cols].copy()
    for c in ["Rent", "ADR", "Gross Revenue", "Monthly Net", "Annual Net", "Startup Cash"]:
        live_display[c] = live_display[c].map(lambda x: f"${x:,.0f}")
    live_display["Occupancy"] = live_display["Occupancy"].map(lambda x: f"{x:.0%}")
    st.dataframe(
        live_display,
        use_container_width=True,
        hide_index=True,
        column_config={"Listing": st.column_config.LinkColumn("Open listing", display_text="View")},
    )

    st.caption("⚠️ Financial figures are estimates. The app intentionally does not treat a high score as legal approval.")

    # -----------------------------
    # Automated research queue
    # -----------------------------
    st.subheader("📋 Your research queue — do this in order")
    candidates = live[(live["Deal Score"] >= minimum_score) & (live["Monthly Net"] > 0)].head(10).copy()
    if candidates.empty:
        st.info("No properties currently meet the financial screening threshold. Lower the minimum score or target profit if you want a wider search.")
    else:
        for idx, row in candidates.iterrows():
            title = f"#{idx + 1} {row.Property} — ${row.Rent:,.0f} rent — ${row['Monthly Net']:,.0f} est. net"
            with st.expander(title, expanded=(idx == candidates.index[0])):
                a, b, c, d = st.columns(4)
                a.metric("Deal score", f"{row['Deal Score']}/100")
                b.metric("Monthly net", f"${row['Monthly Net']:,.0f}")
                c.metric("Break-even", "N/A" if pd.isna(row["Break-even Occupancy"]) else f"{row['Break-even Occupancy']:.0%}")
                d.metric("Startup cash", f"${row['Startup Cash']:,.0f}")

                st.write(f"**Current action:** {row['Action']}")
                st.write(f"**Address:** {row.Address}")
                st.write(f"**Layout:** {int(row.Beds) if float(row.Beds).is_integer() else row.Beds} beds / {int(row.Baths) if float(row.Baths).is_integer() else row.Baths} baths")

                links = research_links(row.Address)
                link_cols = st.columns(6)
                for col, (label, url) in zip(link_cols, links.items()):
                    col.link_button(label, url, use_container_width=True)

                st.markdown("**Ask the landlord/property manager:**")
                questions = [
                    "Does the lease explicitly allow short-term rentals / Airbnb / VRBO?",
                    "Will you provide written permission for short-term rental use?",
                    "Are there building, HOA, condo, or owner-occupancy restrictions?",
                    "Is there a minimum lease term and any subletting restriction?",
                    "Are transient guests or commercial use restricted by the lease?",
                ]
                for q in questions:
                    st.checkbox(q, key=f"q_{idx}_{hash(q)}")

                note = st.text_area("Notes", value=st.session_state.research_notes.get(str(row.Address), ""), key=f"note_{idx}")
                st.session_state.research_notes[str(row.Address)] = note

                message = (
                    f"Hi, I'm interested in {row.Address}. Before applying, I wanted to confirm a few things: "
                    "Does the lease allow short-term rentals such as Airbnb/VRBO, and would you provide written permission for that use? "
                    "Also, are there any HOA/building restrictions, subletting restrictions, or minimum lease terms I should know about? Thanks!"
                )
                st.markdown("**Copy-ready first message:**")
                st.code(message, language="text")

# -----------------------------
# Manual candidates
# -----------------------------
st.divider()
st.subheader(f"🔎 Screen candidate rentals in {city}")
st.write("If you find a property outside RentCast, add it here. It will use the exact same scoring and verification workflow.")

with st.expander("➕ Add a property manually", expanded=False):
    with st.form("manual_property_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            property_name = st.text_input("Property name", placeholder="3BR Apartment")
            address = st.text_input("Address", placeholder="123 Main St, Washington, DC")
            rent = st.number_input("Monthly rent ($)", min_value=0, value=2200, step=50)
            beds = st.number_input("Bedrooms", min_value=0, value=3, step=1)
            baths = st.number_input("Bathrooms", min_value=0.0, value=2.0, step=0.5)
        with c2:
            adr = st.number_input("Estimated nightly rate / ADR ($)", min_value=0, value=150, step=5)
            occupancy_pct = st.number_input("Estimated occupancy (%)", min_value=0, max_value=100, value=65, step=1)
            bookings = st.number_input("Bookings per month", min_value=0, value=8, step=1)
            cleaning_fee = st.number_input("Cleaning fee charged per booking ($)", min_value=0, value=100, step=10)
            cleaning_cost = st.number_input("Cleaning cost per booking ($)", min_value=0, value=60, step=10)
        permission = st.selectbox("Landlord / STR permission", ["Unknown", "Yes", "No"])
        submitted = st.form_submit_button("➕ Add Property", use_container_width=True)
        if submitted:
            if not property_name.strip():
                st.error("Enter a property name first.")
            else:
                st.session_state.manual_properties.append({
                    "Property": property_name.strip(), "Address": address.strip(), "Rent": rent,
                    "Beds": beds, "Baths": baths, "ADR": adr, "Occupancy": occupancy_pct / 100,
                    "Bookings": bookings, "CleaningFee": cleaning_fee, "CleaningCost": cleaning_cost,
                    "Permission": permission,
                })
                st.success(f"Added {property_name.strip()}.")

# -----------------------------
# CSV + combined ranked opportunities
# -----------------------------
st.subheader("📄 Upload candidate properties")
template = pd.DataFrame([
    ["Example 4BR House", "", 2440, 4, 2, 180, 0.65, 8, 120, 100, "Unknown"],
    ["Example 4BR Townhouse", "", 2400, 4, 3, 170, 0.62, 8, 120, 100, "Unknown"],
], columns=["Property", "Address", "Rent", "Beds", "Baths", "ADR", "Occupancy", "Bookings", "CleaningFee", "CleaningCost", "Permission"])

uploaded = st.file_uploader("Upload candidate properties (.csv)", type=["csv"])
if uploaded:
    df = pd.read_csv(uploaded)
    st.success(f"Loaded {len(df)} properties from {uploaded.name}.")
else:
    df = pd.DataFrame(columns=template.columns)

if st.session_state.manual_properties:
    df = pd.concat([df, pd.DataFrame(st.session_state.manual_properties)], ignore_index=True)

if not df.empty:
    required = ["Property", "Rent", "Beds", "Baths", "ADR", "Occupancy", "Bookings", "CleaningFee", "CleaningCost", "Permission"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error("Missing columns: " + ", ".join(missing))
    else:
        for c in ["Rent", "Beds", "Baths", "ADR", "Occupancy", "Bookings", "CleaningFee", "CleaningCost"]:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        if (df["Occupancy"] > 1).any():
            df.loc[df["Occupancy"] > 1, "Occupancy"] = df.loc[df["Occupancy"] > 1, "Occupancy"] / 100

        res = pd.concat([df.reset_index(drop=True), df.apply(calc_row, axis=1)], axis=1)
        res["Source"] = "Manual/CSV"
        res["Action"] = res.apply(action_for, axis=1)
        res = res.sort_values(["Deal Score", "Monthly Net"], ascending=False).reset_index(drop=True)

        st.subheader("🏆 Ranked opportunities")
        cols = ["Property", "Address", "Rent", "Beds", "Baths", "ADR", "Occupancy", "Gross Revenue", "Monthly Net", "Annual Net", "Break-even Occupancy", "Startup Cash", "Deal Score", "Permission", "Action"]
        display = res[cols].copy()
        for c in ["Rent", "ADR", "Gross Revenue", "Monthly Net", "Annual Net", "Startup Cash"]:
            display[c] = display[c].map(lambda x: f"${x:,.0f}")
        for c in ["Occupancy", "Break-even Occupancy"]:
            display[c] = display[c].map(lambda x: "N/A" if pd.isna(x) else f"{x:.0%}")
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.subheader("🧪 Stress test")
        choice = st.selectbox("Choose a property", res.Property.tolist())
        r = res[res.Property == choice].iloc[0]
        scenarios = []
        for label, om, am in [("Bad month", .75, .85), ("Conservative", .85, .90), ("Base", 1, 1), ("Strong", 1.10, 1.10)]:
            occ = min(1, r.Occupancy * om)
            adr = r.ADR * am
            gross = adr * DAYS * occ + r.CleaningFee * r.Bookings
            net = gross * (1 - platform_fee) - r.CleaningCost * r.Bookings - (r.Rent + utilities + insurance + supplies + maintenance + other)
            scenarios.append([label, occ, adr, gross, net])
        stress = pd.DataFrame(scenarios, columns=["Scenario", "Occupancy", "ADR", "Revenue", "Net"])
        stress["Occupancy"] = stress["Occupancy"].map(lambda x: f"{x:.0%}")
        for c in ["ADR", "Revenue", "Net"]:
            stress[c] = stress[c].map(lambda x: f"${x:,.0f}")
        st.table(stress)

# -----------------------------
# Final safety / verification checklist
# -----------------------------
st.divider()
st.subheader("✅ Before signing ANY lease")
checks = [
    "Get written landlord/property-manager approval for short-term rental use.",
    "Confirm the lease allows transient guests, subletting, and commercial use as applicable.",
    "Verify city/county STR licensing, zoning, taxes, occupancy, and primary-residence rules.",
    "Check HOA/condo/building rules and owner-occupancy restrictions.",
    "Confirm insurance covers the intended STR activity.",
    "Verify ADR and occupancy using actual nearby STR comparables.",
    "Keep startup cash plus a reserve for weak months.",
]
for item in checks:
    st.checkbox(item, key="final_" + str(abs(hash(item))))

st.warning(info["legal_note"])
st.info("A high financial score means the numbers look promising — not that the property is legally eligible. Permission and legal verification are separate gates.")
