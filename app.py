
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="Rental Arbitrage Finder", page_icon="🏠", layout="wide")

st.title("🏠 Rental Arbitrage Finder")
st.caption("DMV-focused deal screening for rental arbitrage. Profitability and legal eligibility are evaluated separately.")

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
    city = st.selectbox("Target market", ["Washington, DC", "Silver Spring, MD", "Baltimore, MD"])
    max_rent = st.number_input("Maximum monthly rent", 500, 10000, 2500, 50)
    target_profit = st.number_input("Target monthly profit", 0, 10000, 1000, 100)
    minimum_score = st.slider("Minimum deal score", 0, 100, 70)
    st.header("Operating costs")
    platform_fee = st.slider("Platform fee", 0.0, 0.20, 0.03, 0.005)
    utilities = st.number_input("Utilities + internet / month", 0, 1500, 250, 25)
    insurance = st.number_input("Insurance / month", 0, 500, 75, 10)
    supplies = st.number_input("Supplies / month", 0, 500, 100, 10)
    maintenance = st.number_input("Maintenance reserve / month", 0, 1000, 100, 10)
    other = st.number_input("Other fixed costs / month", 0, 2000, 100, 25)
    furnishing = st.number_input("Furnishing / setup cash", 0, 30000, 5000, 250)

st.subheader(f"🔎 Screen candidate rentals in {city}")
st.write("You can paste candidate properties here or upload a CSV. The app does not scrape Zillow/Airbnb.")

template = pd.DataFrame([
    ["Example 4BR House","",2440,4,2,180,0.65,8,120,100,"Unknown"],
    ["Example 4BR Townhouse","",2400,4,3,170,0.62,8,120,100,"Unknown"],
], columns=["Property","Address","Rent","Beds","Baths","ADR","Occupancy","Bookings","CleaningFee","CleaningCost","Permission"])

uploaded = st.file_uploader("Upload candidate properties (.csv)", type=["csv"])
df = pd.read_csv(uploaded) if uploaded else template.copy()

required = ["Property","Rent","Beds","Baths","ADR","Occupancy","Bookings","CleaningFee","CleaningCost","Permission"]
missing = [c for c in required if c not in df.columns]
if missing:
    st.error("Missing columns: " + ", ".join(missing))
    st.stop()

for c in ["Rent","Beds","Baths","ADR","Occupancy","Bookings","CleaningFee","CleaningCost"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

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
    return pd.Series({
        "Gross Revenue":gross,
        "Monthly Net":net,
        "Annual Net":net*12,
        "Break-even Occupancy":breakeven,
        "Startup Cash":rent+furnishing,
        "Deal Score":score,
    })

res = pd.concat([df, df.apply(calc,axis=1)], axis=1)
res["Status"] = np.where(
    (res.Rent <= max_rent) & (res["Monthly Net"] >= target_profit) & (res["Deal Score"] >= minimum_score),
    "🟢 SHORTLIST",
    np.where(res["Monthly Net"]>0,"🟡 MAYBE","🔴 PASS")
)
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
items = [
"Get written landlord/property-manager approval for short-term rental use.",
"Confirm lease language allows transient guests, subletting, and commercial use as applicable.",
"Verify city/county STR licensing, zoning, taxes, and occupancy requirements.",
"Check HOA/condo/building rules.",
"Confirm insurance covers the intended STR activity.",
"Verify ADR/occupancy using comparable properties rather than relying on a city average.",
"Keep startup cash plus a reserve for weak months.",
]
for item in items:
    st.checkbox(item)

if city == "Washington, DC":
    st.warning("DC is not a simple rent-and-Airbnb market. Current DC rules center on primary-residence licensing, and unhosted vacation rentals are limited to 90 cumulative nights/year. Verify the current law and your exact eligibility before considering a DC arbitrage lease.")

st.info("Market benchmarks are directional only. A high financial score does not mean the property is legally eligible for STR use.")
