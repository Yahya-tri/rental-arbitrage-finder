import streamlit as st
import pandas as pd
import numpy as np
import requests
from urllib.parse import quote_plus

st.set_page_config(page_title="Rental Arbitrage Finder", page_icon="🏠", layout="wide")
DAYS = 30.4

MARKETS = {
    "Washington, DC": {"city":"Washington","state":"DC","adr":239,"occ":0.57,"rule":"DC STR eligibility is restrictive; verify current licensing, primary-residence, zoning, lease and building rules before signing."},
    "Silver Spring, MD": {"city":"Silver Spring","state":"MD","adr":125,"occ":0.60,"rule":"Verify Montgomery County STR licensing, zoning, taxes, lease and building rules."},
    "Baltimore, MD": {"city":"Baltimore","state":"MD","adr":142,"occ":0.57,"rule":"Verify Baltimore City STR licensing, zoning, taxes, lease and building rules."},
}

st.title("🏠 Rental Arbitrage Finder")
st.caption("Find long-term rentals, estimate conservative STR economics, and build a verification queue before you contact a landlord.")

for k,v in {"live":pd.DataFrame(),"manual":[]}.items():
    if k not in st.session_state: st.session_state[k]=v

with st.sidebar:
    st.header("🎯 Search")
    market = st.selectbox("Market", list(MARKETS))
    info = MARKETS[market]
    max_rent = st.number_input("Max monthly rent",500,10000,2500,50)
    min_beds = st.number_input("Minimum bedrooms",0,10,2,1)
    max_beds = st.number_input("Maximum bedrooms",int(min_beds),10,max(4,int(min_beds)),1)
    days_old = st.number_input("Listing age (days)",1,180,30,1)
    property_types = st.multiselect("Property types",["Single Family","Condo","Townhouse","Apartment","Multi-Family"],default=["Single Family","Condo","Townhouse","Apartment"])
    st.header("💰 Costs")
    platform_fee = st.slider("Platform fee",0.0,0.20,0.03,0.005)
    utilities = st.number_input("Utilities + internet",0,1500,250,25)
    insurance = st.number_input("Insurance",0,500,75,10)
    supplies = st.number_input("Supplies",0,500,100,10)
    maintenance = st.number_input("Maintenance reserve",0,1000,100,10)
    other = st.number_input("Other fixed costs",0,2000,100,25)
    furnishing = st.number_input("Furnishing/setup cash",0,30000,5000,250)
    st.header("🏆 Your target")
    target_profit = st.number_input("Target monthly profit",0,10000,1000,100)
    min_score = st.slider("Minimum score",0,100,70)


def fnum(x,d=0):
    try:return float(x)
    except:return d

def search_url(q): return "https://www.google.com/search?q="+quote_plus(q)

def estimate(address,rent,beds,baths,listing):
    # Conservative market estimate; never use the city average without a bedroom adjustment.
    mult={0:.65,1:.78,2:.92,3:1.10,4:1.25,5:1.38}.get(int(beds),1.45)
    adr=info["adr"]*mult
    occ=min(.72,max(.45,info["occ"] + (.02 if beds>=3 else 0)))
    bookings=max(1,round(occ*DAYS/4.0))
    clean_fee=100; clean_cost=60
    gross=adr*DAYS*occ+clean_fee*bookings
    fixed=rent+utilities+insurance+supplies+maintenance+other
    net=gross*(1-platform_fee)-clean_cost*bookings-fixed
    # downside case: ADR -15%, occupancy -15 percentage points (floor 40%).
    bad_occ=max(.40,occ-.15); bad_adr=adr*.85
    bad_gross=bad_adr*DAYS*bad_occ+clean_fee*bookings
    bad_net=bad_gross*(1-platform_fee)-clean_cost*bookings-fixed
    contribution=adr*(1-platform_fee)
    breakeven=np.nan if contribution<=0 else max(0,(fixed+clean_cost*bookings-clean_fee*bookings*(1-platform_fee))/(DAYS*contribution))
    # Score is deliberately harder to game: downside profit and rent burden matter.
    score=0
    score += np.clip(net/max(target_profit,1)*30,0,30)
    score += np.clip(bad_net/max(target_profit,1)*25,0,25)
    score += np.clip(net/max(gross,1)*20,0,20)
    score += 15 if rent<=max_rent else 0
    score += 10 if beds>=3 and baths>=2 else (5 if beds>=2 and baths>=1 else 0)
    score=int(round(min(100,score)))
    return dict(Property=address,Address=address,Rent=rent,Beds=beds,Baths=baths,ADR=adr,Occupancy=occ,Bookings=bookings,CleaningFee=clean_fee,CleaningCost=clean_cost,**{"Gross Revenue":gross,"Monthly Net":net,"Downside Net":bad_net,"Annual Net":net*12,"Break-even Occupancy":breakeven,"Startup Cash":rent+furnishing,"Deal Score":score},Listing=listing,Source="RentCast")

def action(r):
    if r["Monthly Net"]<=0:return "🔴 PASS"
    if r["Downside Net"]<=0:return "🟠 RISKY — loses money in downside"
    if r["Deal Score"]>=min_score:return "🟡 VERIFY — contact only after STR check"
    return "⚪ MAYBE — below target"

st.subheader("🌐 Live rental search")
with st.expander("🔑 RentCast connection",expanded=False):
    api_key=st.text_input("RentCast API key",type="password")
    st.caption("Your key is used only in this session. Never paste it into GitHub.")

if st.button("🔎 Find & rank listings",type="primary",use_container_width=True):
    if not api_key.strip(): st.warning("Enter your RentCast API key first.")
    else:
        params={"city":info["city"],"state":info["state"],"price":f"*:{int(max_rent)}","bedrooms":f"{int(min_beds)}:{int(max_beds)}","daysOld":f"*:{int(days_old)}","limit":50}
        try:
            r=requests.get("https://api.rentcast.io/v1/listings/rental/long-term",params=params,headers={"X-Api-Key":api_key.strip(),"Accept":"application/json"},timeout=20)
            if r.status_code in (401,403): st.error(f"RentCast access error ({r.status_code}). Your key may be valid but API billing/subscription may be inactive.")
            elif not r.ok: st.error(f"RentCast error {r.status_code}: {r.text[:400]}")
            else:
                payload=r.json(); records=payload if isinstance(payload,list) else payload.get("listings",payload.get("data",[]))
                rows=[]
                for x in records:
                    # Prefer listing-level fields. Keep unit identifiers when supplied so a building isn't mistaken for one unit.
                    address=x.get("formattedAddress") or x.get("addressLine1") or "Address unavailable"
                    unit=x.get("unit") or x.get("unitNumber")
                    if unit and str(unit).lower() not in address.lower(): address += f" Unit {unit}"
                    rent=fnum(x.get("price",x.get("rent")))
                    beds=fnum(x.get("bedrooms")); baths=fnum(x.get("bathrooms"))
                    ptype=str(x.get("propertyType","")).strip()
                    if rent<=0 or beds<min_beds or beds>max_beds or rent>max_rent: continue
                    if property_types and ptype and ptype not in property_types: continue
                    url=x.get("listingUrl") or x.get("url") or search_url(f'"{address}" rental')
                    rows.append(estimate(address,rent,beds,baths,url)|{"Property Type":ptype,"Days on Market":x.get("daysOnMarket","")})
                df=pd.DataFrame(rows)
                if not df.empty:
                    df["Action"]=df.apply(action,axis=1); df=df.sort_values(["Deal Score","Downside Net","Monthly Net"],ascending=False).reset_index(drop=True)
                st.session_state.live=df
                st.success(f"Found {len(df)} usable listing records after basic filtering.")
        except requests.RequestException as e: st.error(f"Could not reach RentCast: {e}")

if not st.session_state.live.empty:
    df=st.session_state.live
    a,b,c,d=st.columns(4)
    a.metric("Listings",len(df)); b.metric("Score ≥ target",int((df["Deal Score"]>=min_score).sum())); c.metric("Downside still profitable",int((df["Downside Net"]>0).sum())); d.metric("Best score",int(df.iloc[0]["Deal Score"]))
    st.subheader("🏆 Ranked deals")
    cols=["Property","Rent","Beds","Baths","ADR","Occupancy","Gross Revenue","Monthly Net","Downside Net","Annual Net","Startup Cash","Deal Score","Action","Listing"]
    show=df[cols].copy()
    for c in ["Rent","ADR","Gross Revenue","Monthly Net","Downside Net","Annual Net","Startup Cash"]: show[c]=show[c].map(lambda x:f"${x:,.0f}")
    show["Occupancy"]=show["Occupancy"].map(lambda x:f"{x:.0%}")
    st.dataframe(show,use_container_width=True,hide_index=True,column_config={"Listing":st.column_config.LinkColumn("Listing",display_text="View")})

    st.subheader("🔥 Top deals to investigate")
    top=df[df["Deal Score"]>=min_score].head(10)
    if top.empty: st.info("Nothing currently clears your target. Lower the target temporarily if you want to inspect more deals.")
    for i,row in top.iterrows():
        with st.container(border=True):
            st.markdown(f"### #{i+1} {row.Property}")
            c1,c2,c3,c4=st.columns(4)
            c1.metric("Rent",f"${row.Rent:,.0f}"); c2.metric("Base net",f"${row['Monthly Net']:,.0f}"); c3.metric("Downside net",f"${row['Downside Net']:,.0f}"); c4.metric("Score",int(row['Deal Score']))
            st.write(f"**{int(row.Beds)} bed / {int(row.Baths)} bath** • Estimated ADR ${row.ADR:,.0f} • Estimated occupancy {row.Occupancy:.0%}")
            st.warning("Before contacting/signing: verify the exact unit, current rent, landlord permission for STR use, sublease/transient-guest language, HOA/building rules, and local licensing eligibility.")
            q=f'{row.Property} short term rental Airbnb lease landlord'
            st.link_button("🔎 Research exact property",search_url(q))
            st.code(f'''Hi, I'm interested in {row.Property}. Before scheduling, could you confirm whether the landlord permits short-term rental/guest stays (Airbnb/VRBO), subleasing, or operating a short-term-rental business from the unit? If permitted, would that permission be provided in writing in the lease or an addendum?''',language="text")

st.divider()
st.subheader("⚖️ Legal reality check")
st.warning(MARKETS[market]["rule"])
st.info("A projected profit is not approval. The app intentionally requires a separate verification step because rental-arbitrage legality depends on the exact unit, lease, landlord, building/HOA, and local rules.")

st.subheader("➕ Manual property checker")
with st.form("manual"):
    name=st.text_input("Property/address")
    rent=st.number_input("Rent",0,10000,2000,50)
    beds=st.number_input("Beds",0,10,2,1); baths=st.number_input("Baths",0.0,10.0,1.0,.5)
    if st.form_submit_button("Analyze property") and name:
        row=estimate(name,rent,beds,baths,search_url(f'"{name}" rental'))
        st.success(f"Estimated base net: ${row['Monthly Net']:,.0f}/mo | downside: ${row['Downside Net']:,.0f}/mo | score: {row['Deal Score']}/100")
