import argparse, io, re, time
import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = "https://www.screener.in"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
session = requests.Session()
session.headers.update(HEADERS)

def num(v):
    if v is None: return None
    s = str(v).strip().replace(",", "").replace("%", "").replace("₹", "")
    if s in ("", "-", "--", "nan", "None", "NA"): return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None

def table(soup, sid):
    sec = soup.find(id=sid)
    if not sec or not sec.find("table"): return None
    try: return pd.read_html(io.StringIO(str(sec.find("table"))))[0]
    except Exception: return None

def vals(df, patterns):
    if df is None or df.empty: return []
    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip().lower()
        if any(re.search(p, label) for p in patterns):
            return [x for x in (num(v) for v in row.iloc[1:].tolist()) if x is not None]
    return []

def cagr(v):
    if len(v) < 4 or v[-4] <= 0 or v[-1] <= 0: return None
    return ((v[0] / v[3]) ** (1/3) - 1) * 100

def ratio(soup, labels):
    for li in soup.select("#top-ratios li"):
        n, v = li.select_one(".name"), li.select_one(".value")
        if n and v and any(x in n.get_text(" ", strip=True).lower() for x in labels):
            return num(v.get_text(" ", strip=True))
    v = vals(table(soup, "ratios"), [re.escape(x) for x in labels])
    return v[0] if v else None

def company(query):
    r = session.get(BASE + "/api/company/search/", params={"q": query}, timeout=30)
    r.raise_for_status()
    found = r.json()
    if not found: raise ValueError("Company not found on Screener.in")
    item = found[0]
    url = BASE + item["url"]
    page = session.get(url, timeout=30)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")
    h = soup.select_one("h1")
    name = h.get_text(" ", strip=True) if h else item.get("name", query)
    symbol = item["url"].split("/company/")[-1].split("/")[0].upper()

    pl, bs, cf = table(soup,"profit-loss"), table(soup,"balance-sheet"), table(soup,"cash-flow")
    sh, peers = table(soup,"shareholding"), table(soup,"peers")
    sales, profit, eps = cagr(vals(pl,[r"^sales$"])), cagr(vals(pl,[r"^net profit$"])), cagr(vals(pl,[r"^eps$"]))
    roce, roe = ratio(soup,["roce"]), ratio(soup,["roe"])
    de = ratio(soup,["debt to equity","debt/equity"])
    if de is None:
        debt, equity = vals(bs,[r"^borrowings$"]), vals(bs,[r"^total equity$"])
        if debt and equity and equity[-1] > 0: de = debt[0]/equity[0]
    opmv = vals(pl,[r"^opm"])
    opm = opmv[0] if opmv else None

    cfo = vals(cf,[r"cash from operating activit"])
    capex = vals(cf,[r"fixed assets purchased",r"purchase of fixed assets",r"capital expenditure"])
    fcf = None
    if cfo and capex:
        n = min(3,len(cfo),len(capex))
        fcf = all(cfo[-i]-abs(capex[-i]) > 0 for i in range(1,n+1))

    promoter_vals, pledge_vals = vals(sh,[r"^promoters?$"]), vals(sh,[r"pledged"])
    promoter = promoter_vals[0] if promoter_vals else None
    pledged = pledge_vals[0] if pledge_vals else None
    pe = ratio(soup,["stock p/e","price to earning","p/e"])
    industry_pe = None
    if peers is not None and not peers.empty:
        ix = next((i for i,c in enumerate(peers.columns) if "p/e" in str(c).lower()),None)
        if ix is not None:
            pv = [num(x) for x in peers.iloc[:,ix].tolist()]
            pv = [x for x in pv if x is not None and x > 0]
            if pv: industry_pe = sum(pv)/len(pv)
    peg = pe/eps if pe is not None and eps is not None and eps > 0 else None
    if pe is not None and industry_pe is not None and pe > 0:
        valuation = pe < industry_pe
        valnote = "P/E below peer average" if valuation else "P/E at/above peer average"
    elif peg is not None:
        valuation, valnote = peg < 1.5, "Estimated PEG = P/E divided by 3Y EPS CAGR"
    else:
        valuation, valnote = None, "Valuation data unavailable"

    metrics = {
      "Sales growth 3Y":sales,"Profit growth 3Y":profit,"EPS growth 3Y":eps,
      "ROCE":roce,"ROE":roe,"Debt/Equity":de,"OPM":opm,
      "Positive 3Y FCF":fcf,"Promoter holding":promoter,"Pledged holding":pledged,
      "Valuation":valuation
    }
    tests = [
      ("Sales growth 3Y",lambda x:x>15),("Profit growth 3Y",lambda x:x>15),
      ("EPS growth 3Y",lambda x:x>15),("ROCE",lambda x:x>15),("ROE",lambda x:x>15),
      ("Debt/Equity",lambda x:x<0.5),("OPM",lambda x:x>10),
      ("Positive 3Y FCF",lambda x:x is True),("Promoter holding",lambda x:x>35),
      ("Pledged holding",lambda x:x<5),("Valuation",lambda x:x is True)
    ]
    detail, passed, known = {},0,0
    for key, check in tests:
        value=metrics[key]
        if value is None: detail[key]="NA"; continue
        known+=1
        ok=bool(check(value))
        detail[key]="PASS" if ok else "FAIL"
        passed+=int(ok)
    return {"symbol":symbol,"company":name,"score":round(passed/11*100),"passed":passed,
            "known":known,"metrics":metrics,"detail":detail,"pe":pe,"industry_pe":industry_pe,
            "peg":peg,"valnote":valnote,"url":url}

def fmt(v,s=""): return "NA" if v is None else f"{v:.2f}{s}"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--stocks",required=True)
    args=ap.parse_args()
    stocks=list(dict.fromkeys(x.strip() for x in re.split(r"[,;\n]+",args.stocks) if x.strip()))
    if len(stocks)>100: raise SystemExit(f"Maximum 100 companies per run; received {len(stocks)}. Separate names with commas, semicolons, or new lines.")
    out=[]; errors=[]
    print(f"FUNDAMENTAL-ONLY ANALYSIS | Input: {len(stocks)}")
    for s in stocks:
        try:
            x=company(s); out.append(x)
            print(f"Analysed {s}: {x['passed']}/11 ({x['score']}/100)")
        except Exception as e:
            errors.append((s,str(e))); print(f"ERROR {s}: {e}")
        time.sleep(0.7)
    out.sort(key=lambda x:(x["score"],x["known"],x["passed"]),reverse=True)
    lines=["TOP 5 FUNDAMENTAL STOCKS",f"Input: {len(stocks)} | Analysed: {len(out)} | Errors: {len(errors)}",
           "Fundamental ranking only. No technical analysis or intraday signal.", ""]
    for i,x in enumerate(out[:5],1):
        m=x["metrics"]
        lines += [f"{i}. {x['symbol']} - {x['company']}",
          f"Score {x['score']}/100 | Passed {x['passed']}/11 | Data {x['known']}/11",
          f"Sales CAGR {fmt(m['Sales growth 3Y'],'%')} | Profit CAGR {fmt(m['Profit growth 3Y'],'%')} | EPS CAGR {fmt(m['EPS growth 3Y'],'%')}",
          f"ROCE {fmt(m['ROCE'],'%')} | ROE {fmt(m['ROE'],'%')} | D/E {fmt(m['Debt/Equity'])} | OPM {fmt(m['OPM'],'%')}",
          f"3Y FCF positive: {m['Positive 3Y FCF']} | Promoter {fmt(m['Promoter holding'],'%')} | Pledged {fmt(m['Pledged holding'],'%')}",
          f"P/E {fmt(x['pe'])} | Peer P/E {fmt(x['industry_pe'])} | Est. PEG {fmt(x['peg'])} | {x['valnote']}",
          "Checks: "+" | ".join(f"{k}: {v}" for k,v in x["detail"].items()),f"Source: {x['url']}",""]
    if errors: lines += ["NOT ANALYSED:"]+[f"{s}: {e}" for s,e in errors]
    lines += ["NA metrics are not counted as passed. PEG is an estimate, not a published Screener PEG.",
              "Fundamental quality does not guarantee intraday liquidity, volatility, or profit."]
    report="\n".join(lines)
    print(report)
    open("fundamental_top5_report.txt","w",encoding="utf-8").write(report)
    pd.DataFrame([{"Rank":i+1,"Symbol":x["symbol"],"Company":x["company"],"Score":x["score"],
       "Passed":x["passed"],"DataAvailable":x["known"],**x["metrics"],"PE":x["pe"],
       "IndustryPE":x["industry_pe"],"EstimatedPEG":x["peg"],"ScreenerURL":x["url"]}
       for i,x in enumerate(out[:5])]).to_csv("fundamental_top5.csv",index=False)

if __name__=="__main__": main()
