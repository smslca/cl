'''
Get Indices Chage
Each Index how changed and look for volume busters

'''

import datetime
import requests
import pandas as pd
HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "origin": "https://www.niftyindices.com",
    "referer": "https://www.niftyindices.com/",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
}
def get_all_indices():
    url = "https://www.nseindia.com/api/allIndices"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return pd.DataFrame(response.json().get("data"))

def get_total_market_change():
    url = "https://www.nseindia.com/api/NextApi/apiClient/marketWatchApi?functionName=getIndicesData&symbol=NIFTY%20TOTAL%20MKT"

    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    #print(response.json().get("data").get("data"))
    df = pd.DataFrame(response.json().get("data").get("data"))
    return df
    
def get_index_constituents(index_name):
    url = f"https://www.nseindia.com/api/heatmap-symbols?indices={index_name}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    temp_df = pd.DataFrame(response.json())
    temp_df["index_name"] = index_name
    return temp_df

def get_filtered_indices_constituents():
    df = pd.read_csv("../Data/nse_indices_filter.csv")
    all_constituents = pd.DataFrame()
    for index, row in df.iterrows():
        index_name = row["indexSymbol"]
        constituents = get_index_constituents(index_name)
        all_constituents = pd.concat([all_constituents, constituents])
    return all_constituents

all_constituents = get_filtered_indices_constituents()
# index_name,symbol,lastPrice,pChange,totalTradedVolume,VWAP
all_constituents = all_constituents[["index_name","symbol","lastPrice","pChange","totalTradedVolume","VWAP"]]
all_constituents.to_csv(f"../out/filterd_indices_constituents_{datetime.datetime.now().strftime('%Y%m%d')}.csv", index=False)

df = pd.read_csv("../Data/nse_indices_filter.csv")
tm_list = pd.read_csv("../Data/total_market_index_list.csv")


all_indices = get_all_indices()
all_indices_filtered = all_indices[all_indices["indexSymbol"].isin(df["indexSymbol"])]
all_indices_filtered['perChange7d'] = round(((all_indices_filtered['last']/all_indices_filtered['oneWeekAgoVal']) -1 ) * 100, 2)
#key,indexSymbol,last,percentChange,declines,advances,pe,unchanged,perChange365d,perChange30d,perChange7d

all_indices_filtered = all_indices_filtered[["key","indexSymbol","last","percentChange","declines","advances","pe","unchanged","perChange365d","perChange30d","perChange7d"]]
all_indices_filtered.to_csv(f"../out/nse_indices_change_{datetime.datetime.now().strftime('%Y%m%d')}.csv", index=False)

total_market_change = get_total_market_change()


total_market_change = total_market_change[["symbol","change","totalTradedVolume","lastPrice","pChange"]]

total_market_change.to_csv(f"../out/total_market_change_{datetime.datetime.now().strftime('%Y%m%d')}.csv", index=False)