import streamlit as st
import pandas as pd
import numpy as np
import requests
from urllib.parse import quote_plus

st.set_page_config(page_title="Rental Arbitrage Finder", page_icon="🏠", layout="wide")

st.title("🏠 Rental Arbitrage Finder")
st.caption("DMV-focused deal screening for rental arbitrage. Profitability and legal eligibility are evaluated separately.")

CITY_INFO = {
    "Washington, DC": {"city": "Washington", "state": "DC", "adr": 239, "occ": 0.57},
    "Silver Spring, MD": {"city": "Silver Spring", "state": "MD", "adr": 125, "occ": 0.60},
    "Baltimore, MD": {"city": "Baltimore", "state": "MD", "adr": 142, "occ": 0.57},
}

st.subheader("DMV starter market benchmarks")
bench = pd.DataFrame([
    ["Washington, DC", 239, 0.57, 23700, "High demand; STR rules are restrictive"],
    ["Silver Spring, MD", 125, 0.60, 12200, "County rules/licensing must be checked"],
    ["Baltimore, MD", 142, 0.57, 15500, "Useful comparison market"],
], columns=["Market","ADR","Occupancy","Annual Revenue","Note"])
show = bench.copy()
show["ADR"] = show["ADR"].map(lambda x:f"${x:,.0f}")
show["Occupancy"] = show["Occupancy"].map(lambda x:f"{x:.0%}")
show["Annual Revenue"] = show["Annual Revenue"].map(lambda x:f"${x:,.0f}")
st.dataframe(show, use_container_width=True, hide_index=True)

with st.sidebar:
    st.header("Your criteria")
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
    st.header("Operating costs")
    platform_fee = st.slider("Platform fee", 0.0, 0.20, 0.03, 0.005)
    utilities = st.number_input("Utilities + internet / month", 0, 1500, 250, 25)
    insurance = st.number_input("Insurance / month", 0, 500, 75, 10)
    supplies = st.number_input("Supplies / month", 0, 500, 100, 10)
    maintenance = st.number_input("Maintenance reserve / month", 0, 1000, 100, 10)
    other = st.number_input("Other fixed costs / month", 0, 2000, 100, 25)
    furnishing = st.number_input("Furnishing / setup cash", 0, 30000, 5000, 250)

st.divider()

# Live listing search using an optional RentCast API key.
st.subheader(f"🌐 Find live rental listings in {city}")
st.write("This searches active long-term rental listings and sends the results through the same arbitrage calculator. Live listing data requires a RentCast API key.")

with st.expander("🔑 Connect live listing search", expanded=False):
    api_key = st.text_input("RentCast API key", type="password", help="Your key is used only for this Streamlit session and is not written into GitHub.")
    st.caption("The app uses the RentCast rental-listings endpoint. Do not paste your API key into app.py or commit it to GitHub.")

if "live_listings" not in st.session_state:
    st.session_state.live_listings = pd.DataFrame()

search_clicked = st.button("🔎 Find rental listings", type="primary", use_container_width=True)

if search_clicked:
    if not api_key.strip():
        st.warning("Enter your RentCast API key above first.")
    else:
        info = CITY_INFO[city]
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
            if response.status_code == 401:
                st.error("RentCast rejected the API key. Check that it is active and copied correctly.")
            elif not response.ok:
                st.error(f"RentCast returned HTTP {response.status_code}: {response.text[:300]}")
            else:
                payload = response.json()
                records = payload if isinstance(payload, list) else payload.get("listings", payload.get("data", []))
                rows = []
                for x in records:
                    rent_value = x.get("price", x.get("rent", 0))
                    beds_value = x.get("bedrooms", 0)
                    baths_value = x.get("bathrooms", 0)
                    try:
                        rent_value = float(rent_value or 0)
                    except (TypeError, ValueError):
                        rent_value = 0
                    try:
                        beds_value = float(beds_value or 0)
                    except (TypeError, ValueError):
                        beds_value = 0
                    try:
                        baths_value = float(baths_value or 0)
                    except (TypeError, ValueError):
                        baths_value = 0

                    # Directional STR revenue estimate. Replace with local comp data before signing a lease.
                    bed_multiplier = {0: 0.65, 1: 0.78, 2: 0.92, 3: 1.15, 4: 1.35}.get(int(beds_value), 1.50)
                    estimated_adr = info["adr"] * bed_multiplier
                    estimated_occ = min(0.80, info["occ"] + max(0, beds_value - 2) * 0.02)
                    bookings = max(1, round(estimated_occ * 30.4 / 3.5))
                    cleaning_fee = 100
                    cleaning_cost = 60
                    gross = estimated_adr * 30.4 * estimated_occ + cleaning_fee * bookings
                    net = gross * (1 - platform_fee) - cleaning_cost * bookings - (rent_value + utilities + insurance + supplies + maintenance + other)
                    startup = rent_value + furnishing
                    profit_score = np.clip((net / max(target_profit, 1)) * 40, 0, 40)
                    margin_score = np.clip((net / max(gross, 1)) * 25, 0, 25)
                    rent_score = 15 if rent_value <= max_rent else 0
                    score = int(round(min(100, profit_score + margin_score + rent_score)))
                    address = x.get("formattedAddress") or x.get("addressLine1") or "Address unavailable"
                    direct_url = x.get("listingUrl") or x.get("url") or x.get("website")
                    if not direct_url:
                        direct_url = "https://www.google.com/search?q=" + quote_plus(address + " rental")
                    rows.append({
                        "Property": address,
                        "Address": address,
                        "Rent": rent_value,
                        "Beds": beds_value,
                        "Baths": baths_value,
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
                        "Startup Cash": startup,
                        "Deal Score": score,
                    })
                st.session_state.live_listings = pd.DataFrame(rows)
                st.success(f"Found {len(rows)} rental listings matching your filters.")
        except requests.RequestException as e:
            st.error(f"Could not reach RentCast: {e}")

if not st.session_state.live_listings.empty:
    live = st.session_state.live_listings.copy().sort_values(["Deal Score", "Monthly Net"], ascending=False)
    st.subheader("🔥 Live listings ranked by estimated arbitrage potential")
    live_display = live[["Property","Rent","Beds","Baths","ADR","Occupancy","Gross Revenue","Monthly Net","Annual Net","Startup Cash","Deal Score","Property Type","Days on Market","Listing"]].copy()
    for c in ["Rent","ADR","Gross Revenue","Monthly Net","Annual Net","Startup Cash"]:
        live_display[c] = live_display[c].map(lambda x: f"${x:,.0f}")
    live_display["Occupancy"] = live_display["Occupancy"].map(lambda x: f"{x:.0%}")
    live_display["Listing"] = live_display["Listing"].fillna("")
    st.dataframe(
        live_display,
        use_container_width=True,
        hide_index=True,
        column_config={"Listing": st.column_config.LinkColumn("Open listing", display_text="View")},
    )
    st.caption("⚠️ ADR, occupancy, bookings, and profit are estimates based on the selected market benchmark and bedroom count. Verify comparable STR revenue and legal eligibility before spending money or signing a lease.")

st.divider()
st.subheader(f"🔎 Screen candidate rentals in {city}")
st.write("Add a property manually below, or upload a CSV with multiple properties.")

if "manual_properties" not in st.session_state:
    st.session_state.manual_properties = []

with st.expander("➕ Add a property manually", expanded=True):
    with st.form("manual_property_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            property_name = st.text_input("Property name", placeholder="3BR Apartment")
            address = st.text_input("Address", placeholder="123 Main St, Silver Spring, MD")
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
                    "Property": property_name.strip(),
                    "Address": address.strip(),
                    "Rent": rent,
                    "Beds": beds,
                    "Baths": baths,
                    "ADR": adr,
                    "Occupancy": occupancy_pct / 100,
                    "Bookings": bookings,
                    "CleaningFee": cleaning_fee,
                    "CleaningCost": cleaning_cost,
                    "Permission": permission,
                })
                st.success(f"Added {property_name.strip()} to the analysis.")

if st.session_state.manual_properties:
    st.write("**Manually added properties:**")
    manual_preview = pd.DataFrame(st.session_state.manual_properties)
    manual_preview["Occupancy"] = manual_preview["Occupancy"].map(lambda x: f"{x:.0%}")
    st.dataframe(manual_preview, use_container_width=True, hide_index=True)

st.divider()
st.subheader("📄 Upload candidate properties")
template = pd.DataFrame([
    ["Example 4BR House","",2440,4,2,180,0.65,8,120,100,"Unknown"],
    ["Example 4BR Townhouse","",2400,4,3,170,0.62,8,120,100,"Unknown"],
], columns=["Property","Address","Rent","Beds","Baths","ADR","Occupancy","Bookings","CleaningFee","CleaningCost","Permission"])

uploaded = st.file_uploader("Upload candidate properties (.csv)", type=["csv"])
if uploaded:
    df = pd.read_csv(uploaded)
    st.success(f"Loaded {len(df)} properties from {uploaded.name}.")
else:
    df = template.copy()

if st.session_state.manual_properties:
    df = pd.concat([df, pd.DataFrame(st.session_state.manual_properties)], ignore_index=True)

required = ["Property","Rent","Beds","Baths","ADR","Occupancy","Bookings","CleaningFee","CleaningCost","Permission"]
missing = [c for c in required if c not in df.columns]
if missing:
    st.error("Missing columns: " + ", ".join(missing))
    st.stop()

for c in ["Rent","Beds","Baths","ADR","Occupancy","Bookings","CleaningFee","CleaningCost"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
if (df["Occupancy"] > 1).any():
    df.loc[df["Occupancy"] > 1, "Occupancy"] = df.loc[df["Occupancy"] > 1, "Occupancy"] / 100

DAYS = 30.4

def calc(r):
    rent = float(r.Rent)
    adr = float(r.ADR)
    occ = min(max(float(r.Occupancy),0),1)
    bookings = float(r.Bookings)
    gross = adr*DAYS*occ + float(r.CleaningFee)*bookings
    platform = gross*platform_fee
    cleaning = float(r.CleaningCost)*bookings
    fixed = rent+utilities+insurance+supplies+maintenance+other
    net = gross-platform-cleaning-fixed
    contribution = adr*(1-platform_fee)
    breakeven = np.nan
    if contribution > 0:
        breakeven = max(0, (fixed+cleaning-float(r.CleaningFee)*bookings*(1-platform_fee))/(DAYS*contribution))
    profit_score = np.clip((net/max(target_profit,1))*40,0,40)
    margin_score = np.clip((net/max(gross,1))*25,0,25)
    cushion_score = 0 if np.isnan(breakeven) else np.clip((occ-breakeven)*50,0,20)
    rent_score = 15 if rent <= max_rent else 0
    score = min(100, round(profit_score+margin_score+cushion_score+rent_score))
    return pd.Series({"Gross Revenue":gross,"Monthly Net":net,"Annual Net":net*12,"Break-even Occupancy":breakeven,"Startup Cash":rent+furnishing,"Deal Score":score})

res = pd.concat([df, df.apply(calc,axis=1)], axis=1)
res["Status"] = np.where((res.Rent <= max_rent) & (res["Monthly Net"] >= target_profit) & (res["Deal Score"] >= minimum_score), "🟢 SHORTLIST", np.where(res["Monthly Net"]>0,"🟡 MAYBE","🔴 PASS"))
res = res.sort_values(["Deal Score","Monthly Net"], ascending=False)

st.subheader("🏆 Ranked opportunities")
cols = ["Property","Address","Rent","Beds","Baths","ADR","Occupancy","Gross Revenue","Monthly Net","Annual Net","Break-even Occupancy","Startup Cash","Deal Score","Permission","Status"]
display = res[cols].copy()
for c in ["Rent","ADR","Gross Revenue","Monthly Net","Annual Net","Startup Cash"]:
    display[c] = display[c].map(lambda x:f"${x:,.0f}")
for c in ["Occupancy","Break-even Occupancy"]:
    display[c] = display[c].map(lambda x:"N/A" if pd.isna(x) else f"{x:.0%}")
st.dataframe(display, use_container_width=True, hide_index=True)

st.subheader("🧪 Stress test")
choice = st.selectbox("Choose a property", res.Property.tolist())
r = res[res.Property==choice].iloc[0]
scenarios = []
for label, om, am in [("Bad month",.75,.85),("Conservative",.85,.90),("Base",1,1),("Strong",1.10,1.10)]:
    occ = min(1,r.Occupancy*om)
    adr = r.ADR*am
    gross = adr*DAYS*occ + r.CleaningFee*r.Bookings
    net = gross*(1-platform_fee)-r.CleaningCost*r.Bookings-(r.Rent+utilities+insurance+supplies+maintenance+other)
    scenarios.append([label,occ,adr,gross,net])
stress = pd.DataFrame(scenarios,columns=["Scenario","Occupancy","ADR","Revenue","Net"])
stress["Occupancy"]=stress["Occupancy"].map(lambda x:f"{x:.0%}")
for c in ["ADR","Revenue","Net"]:
    stress[c]=stress[c].map(lambda x:f"${x:,.0f}")
st.table(stress)

st.subheader("✅ Required checks before signing")
for item in [
"Get written landlord/property-manager approval for short-term rental use.",
"Confirm lease language allows transient guests, subletting, and commercial use as applicable.",
"Verify city/county STR licensing, zoning, taxes, and occupancy requirements.",
"Check HOA/condo/building rules.",
"Confirm insurance covers the intended STR activity.",
"Verify ADR/occupancy using comparable properties rather than relying on a city average.",
"Keep startup cash plus a reserve for weak months.",
]:
    st.checkbox(item)

if city == "Washington, DC":
    st.warning("DC is not a simple rent-and-Airbnb market. Current DC rules center on primary-residence licensing, and unhosted vacation rentals are limited to 90 cumulative nights/year. Verify the current law and your exact eligibility before considering a DC arbitrage lease.")

st.info("Market benchmarks are directional only. A high financial score does not mean the property is legally eligible for STR use.")
