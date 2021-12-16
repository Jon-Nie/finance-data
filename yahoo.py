import datetime as dt
import pandas as pd
import numpy as np
import requests
import re
from finance_data.utils import (
    TickerError,
    DatasetError,
    HEADERS,
    CAMEL_TO_SPACE,
    PLACEHOLDER_LOGO,
    SERVER_ERROR_MESSAGE
)

class YahooReader:
    _crumb_url = "https://query1.finance.yahoo.com/v1/test/getcrumb"
    _currencies_url = "https://query1.finance.yahoo.com/v1/finance/currencies"
    
    _main_url = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{}"
    _price_url = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
    _estimates_url = "https://finance.yahoo.com/quote{}/analysis"
    _options_url = "https://query1.finance.yahoo.com/v7/finance/options/{}"
    _esg_ts_url = "https://query1.finance.yahoo.com/v1/finance/esgChart"

    @classmethod
    def crumb(cls) -> str:
        data = requests.get(
            url = cls._crumb_url,
            headers = HEADERS
        ).text
        
        return data
    
    @classmethod
    def currencies(cls) -> list:
        data = requests.get(
            url = cls._currencies_url,
            headers = HEADERS
        ).json()
        
        data = data["currencies"]["result"]
        data = [
            {
                "short_name": item["shortName"],
                "long_name": item["longName"],
                "symbol": item["symbol"]
            }
            for item in data
        ]
        
        return data

    def __init__(
        self,
        ticker: str = None,
        isin: str = None
    ) -> None:
        if ticker:
            self._ticker = ticker.upper()
        elif isin:
            response = requests.get(
                url = f"https://markets.businessinsider.com/ajax/SearchController_Suggest?max_results=1&query={isin}",
                headers = HEADERS
            ).text
            try:
                self._ticker = re.findall(f"\|{isin}\|([A-Z0-9]+)\|", response)[0]
            except IndexError as e:
                raise ValueError("Cannot find a ticker that belongs to the given isin")
        else:
            raise ValueError("Either ticker or isin has to be specified")
        self._stored_data = self._get_stored_data()
        
        self._security_type = self._stored_data["quoteType"]["quoteType"]
        self._name = self._stored_data["quoteType"]["shortName"]

    @property
    def ticker(self):
        return self._ticker
    
    @property
    def name(self):
        return self._name
    
    @property
    def security_type(self):
        return self._security_type

    @property
    def isin(self):
        if not hasattr(self, "_isin"):
            ticker_dot = self.ticker.replace('-', '.')
            response = requests.get(
                url = f"https://markets.businessinsider.com/ajax/SearchController_Suggest?max_results=1&query={ticker_dot}",
                headers = HEADERS
            ).text
            try:
                self._isin = re.findall(f"{ticker_dot}\|([A-Z0-9]+)\|{ticker_dot}", response)[0]
            except IndexError:
                self._isin = None
        return self._isin
        
    def profile(self) -> dict:        
        try:
            data = self._stored_data["assetProfile"].copy()
        except:
            raise DatasetError(f"no profile found for ticker {self.ticker}")
        
        for key in (
            "address1",
            "address2",
            "longBusinessSummary"
        ):
            if key in data.keys():
                data[key] = data[key].encode("latin1").decode().replace("\n ", "\n")
        
        data["employees"] = data.pop("fullTimeEmployees")
        data["description"] = data.pop("longBusinessSummary")
        if "website" in data.keys():
            data["website"] = data["website"].replace("http:", "https:")
        data["executives"] = [
            {
                "name": entry["name"],
                "age": entry["age"] if "age" in entry else None,
                "position": entry["title"],
                "born": entry["yearBorn"] if "yearBorn" in entry else None,
                "salary": entry["totalPay"]["raw"] if "totalPay" in entry else None,
                "exersized_options": entry["exercisedValue"]["raw"],
                "unexersized_options": entry["unexercisedValue"]["raw"]
            }
            for entry in data["companyOfficers"]
        ]
        for key in (
            "companyOfficers",
            "auditRisk",
            "boardRisk",
            "compensationRisk",
            "shareHolderRightsRisk",
            "overallRisk",
            "governanceEpochDate",
            "compensationAsOfEpochDate",
            "maxAge"
        ):
            if key in data.keys():
                data.pop(key)
        return data

    def logo(self) -> bytes:
        response = requests.get(
            url = f"https://storage.googleapis.com/iex/api/logos/{self.ticker.replace('-', '.')}.png",
            headers = HEADERS
        ).content
        if response == PLACEHOLDER_LOGO or response == SERVER_ERROR_MESSAGE:
            if "website" in self.profile().keys():
                response = requests.get(
                    url = f"https://logo.clearbit.com/{self.profile()['website']}",
                    headers = HEADERS
                ).content
            else:
                response = b"\n"
        return response
    
    def historical_data(
        self,
        frequency = '1d',
        start = dt.datetime(1900, 1, 1),
        end = dt.datetime.today(),
        returns = True,
        timestamps = False,
        rounded = False,
        tz_aware = False
    ) -> dict:

        """
        frequency : str
            1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
            default: 1d

        period : str
            1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, max, ytd
            default: None
        
        start : str, integer, datetime.date or datetime.datetime object
            str input has to be in ISO-format: YYYY-mm-dd
            default: dt.date(1970, 1, 1)

        end : str, integer, datetime.date or datetime.datetime object
            str input has to be in ISO-format: YYYY-mm-dd
            default: datetime.date.today()
        
        returns : bool
            If True, computes simple and log returns of the adjusted closing price series
            default: True

        timestamps : bool
            If True, df.index has timestamps. If False, df.index has tz-aware datetime objects
            default: False
        
        rounded : bool
            If True, prices are rounded to two decimal points
            default : False
        
        tz_aware : bool
            If True and frequency is set to less than a day, datetimes are timezone-aware
            default : True        
        """

        if isinstance(start, str):
            start = int((dt.date.fromisoformat(start) - dt.date(1970, 1, 1)).total_seconds())
        elif isinstance(start, dt.datetime):
            start = int((start - dt.datetime(1970, 1, 1)).total_seconds())
        elif isinstance(start, dt.date):
            start = int((start - dt.date(1970, 1, 1)).total_seconds())
        
        if isinstance(end, str):
            end = int((dt.date.fromisoformat(end) - dt.date(1970, 1, 1)).total_seconds())
        elif isinstance(end, dt.datetime):
            end = int((end - dt.datetime(1970, 1, 1)).total_seconds())
        elif isinstance(end, dt.date):
            end = int((end - dt.date(1970, 1, 1)).total_seconds())
        

        parameters = {
            "period1": start,
            "period2": end,
            "interval": frequency,
            "events": "dividends,splits",
            "includeAdjustedClose": True
        }

        data = requests.get(
            url = self._price_url.format(self.ticker),
            params = parameters,
            headers = HEADERS
        )

        url = data.url
        data = data.json()
        
        meta_data = data["chart"]["result"][0]["meta"]
        currency = meta_data["currency"]
        type_ = meta_data["instrumentType"]
        utc_offset = meta_data["gmtoffset"]
        timezone = meta_data["timezone"]
        exchange_timezone = meta_data["exchangeTimezoneName"]
        tz_offset = meta_data["gmtoffset"]
        
        ts = data["chart"]["result"][0]["timestamp"]
        history = data["chart"]["result"][0]["indicators"]["quote"][0]
        
        # dividend and split data
        if "events" in data["chart"]["result"][0]:
            events = data["chart"]["result"][0]["events"]

            # dividends
            if "dividends" in events:
                dividends = events["dividends"]
                dividends = [(div["date"], div["amount"]) for div in dividends.values()]
                dividends = list(zip(*dividends))

                df_div = pd.DataFrame(
                    data = dividends[1],
                    columns = ["dividends"],
                    index = dividends[0]
                )
            else:
                df_div = pd.DataFrame(columns = ["dividends"])
            
            # splits
            if "splits" in events:
                splits = events["splits"]
                splits = [(split["date"], split["numerator"]/split["denominator"]) for split in splits.values()]
                splits = list(zip(*splits))

                df_splits = pd.DataFrame(
                    data = splits[1],
                    columns = ["splits"],
                    index = splits[0]
                )
            else:
                df_splits = pd.DataFrame(columns = ["splits"])
            
        else:
            df_div = pd.DataFrame(columns = ["dividends"])
            df_splits = pd.DataFrame(columns = ["splits"])

        # price and volume data
        open_ = history["open"]
        high = history["high"]
        low = history["low"]
        close = history["close"]
        volume = history["volume"]
        
        if "adjclose" in data["chart"]["result"][0]["indicators"]:
            adj_close = data["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"]
        else:
            adj_close = close

        prices = pd.DataFrame(
            data = {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "adj close": adj_close,
                "volume": volume
            },
            index = ts
        )
        if rounded:
            prices[["open", "high", "low", "close", "adj close"]] = prices[["open", "high", "low", "close", "adj close"]].round(2)
        
        if not timestamps:
            if frequency in ("1d", "1wk", "1mo", "3mo"):
                prices.index = [dt.date(1970,1,1) + dt.timedelta(seconds=ts + tz_offset) for ts in prices.index]
                df_div.index = [dt.date(1970,1,1) + dt.timedelta(seconds=ts + tz_offset) for ts in df_div.index]
                df_splits.index = [dt.date(1970,1,1) + dt.timedelta(seconds=ts + tz_offset) for ts in df_splits.index]
            else:
                prices.index = [dt.datetime(1970,1,1) + dt.timedelta(seconds=ts) for ts in prices.index]
                df_div.index = [dt.datetime(1970,1,1) + dt.timedelta(seconds=ts) for ts in df_div.index]
                df_splits.index = [dt.datetime(1970,1,1) + dt.timedelta(seconds=ts) for ts in df_splits.index]
                if tz_aware:
                    prices.index = prices.index.tz_localize(timezone)
                    df_div.index = df_div.index.tz_localize(timezone)
                    df_splits.index = df_splits.index.tz_localize(timezone)

        if prices.index[-1] == prices.index[-2]:
            prices = prices[:-1]
        
        # merge prices with dividends
        df = pd.concat([prices, df_div], axis=1)
        df = df.sort_index()
        
        if frequency in ("1wk", "1mo", "3mo"):
            dividends = df["dividends"].copy()
            for i in range(len(dividends)-1):
                if not np.isnan(dividends.iloc[i]) and np.isnan(dividends.iloc[i+1]) and np.isnan(df.loc[df.index[i], "close"]):
                    df.loc[df.index[i+1], "dividends"] = df.loc[df.index[i], "dividends"]
            df = df[df["close"].notna()]
        
        # merge prices, dividends with splits
        df = pd.concat([df, df_splits], axis=1)
        df = df.sort_index()
        
        if frequency in ("1wk", "1mo", "3mo"):
            splits = df["splits"].copy()
            for i in range(len(splits)-1):
                if not np.isnan(splits.iloc[i]) and np.isnan(splits.iloc[i+1]) and np.isnan(df.loc[df.index[i], "close"]):
                    df.loc[df.index[i+1], "splits"] = df.loc[df.index[i], "splits"]
            df = df[df["close"].notna()]

        if returns:
            df['simple returns'] = (df['close'] + df['dividends'].fillna(0)) / df['close'].shift(1) - 1
            df['log returns'] = np.log((df['close'] + df['dividends'].fillna(0)) / df['close'].shift(1))

        if timestamps:
            df.index.name = "timestamps"
        elif frequency in ("1d", "1wk", "1mo", "3mo"):
            df.index.name = "date"
        else:
            df.index.name = "datetime"
        
        return {
            "data": df,
            "information": {
                "type": type_,
                "currency": currency,
                "utc_offset": utc_offset,
                "timezone": timezone,
                "exchange_timezone": exchange_timezone,
                "url": url,
            }
        }
    
    def analyst_recommendations(
        self,
        timestamps = False
    ) -> list:
        try:
            data = self._stored_data["upgradeDowngradeHistory"]["history"]
        except:
            raise DatasetError(f"no analyst ratings found for ticker {self.ticker}")
        data = [
            {
                "date": (dct["epochGradeDate"] if timestamps
                         else (dt.date(1970, 1, 1) + dt.timedelta(seconds = dct["epochGradeDate"])).isoformat()),
                "firm": dct["firm"],
                "new": dct["toGrade"],
                "old": dct["fromGrade"],
                "change": dct["action"]
            }
            for dct in data
        ]
        
        return data
    
    def recommendation_trend(self) -> dict:
        try:
            data = self._stored_data["recommendationTrend"]["trend"]
        except:
            raise DatasetError(f"no recommendation trend found for ticker {self.ticker}")
        data = {
            entry["period"]: {
                "count": int(entry["strongBuy"] + entry["buy"] + entry["hold"] + entry["sell"] + entry["strongSell"]),
                "average": (
                    (entry["strongBuy"] * 5 + entry["buy"] * 4 + entry["hold"] * 3 + entry["sell"] * 2 + entry["strongSell"] * 1)
                    / (entry["strongBuy"] + entry["buy"] + entry["hold"] + entry["sell"] + entry["strongSell"])
                    if (entry["strongBuy"] + entry["buy"] + entry["hold"] + entry["sell"] + entry["strongSell"]) != 0 else None
                ),
                "strong_buy": entry["strongBuy"],
                "buy": entry["buy"],
                "hold": entry["hold"],
                "sell": entry["sell"],
                "strong_sell": entry["strongSell"]
            }
            for entry in data
        }
        
        data["today"] = data.pop("0m")
        data["-1month"] = data.pop("-1m")
        data["-2months"] = data.pop("-2m")
        data["-3months"] = data.pop("-3m")
        
        return data
    
    def options(
        self,
        date = None,
        strike_min = None,
        strike_max = None,
        timestamps = False
    ) -> dict:
        """
        date : int
            If date is set to an integer, only options with that specific maturity date are returned
            default : None
        
        strike_min: int or float
            Sets the minimum strike price so that only option data with strike prices above the minimum strike are returned
            default : None
        
        strike_max: int or float
            Sets the maximum strike price so that only option data with strike prices below the maximum strike are returned
            default : None
        
        timestamps : bool
            If True, dict keys are isoformatted date strings. If False, dict keys are unix timestamps
            default: False
        """

        parameters = {
            "getAllData": True,
            "date": date,
            "strikeMin": strike_min,
            "strikeMax": strike_max
        }

        options_list = requests.get(
            url = self._options_url.format(self.ticker),
            headers = HEADERS,
            params = parameters
        ).json()
        
        try:
            options_list = options_list["optionChain"]["result"][0]["options"]
        except:
            raise TickerError(f"no options found for ticker {self.ticker}")
        
        options = {"calls": [], "puts": []}
        for dct in options_list:
            if timestamps:
                date = dct["expirationDate"]
            else:
                date = (dt.date(1970, 1, 1) + dt.timedelta(seconds = dct["expirationDate"])).isoformat()

            for call in dct["calls"]:
                data = {}
                data["maturity"] = date
                data["strike"] = call["strike"]
                data["symbol"] = call["contractSymbol"]
                data["last_price"] = call["lastPrice"]
                if "bid" in call.keys():
                    data["bid"] = call["bid"]
                else:
                    data["bid"] = None
                if "ask" in call.keys():
                    data["ask"] = call["ask"]
                else:
                    data["ask"] = None
                if "volume" in call.keys():
                    data["volume"] = call["volume"]
                else:
                    data["volume"] = None
                data["implied_volatility"] = call["impliedVolatility"]
                data["itm"] = call["inTheMoney"]
            
                options["calls"].append(data)
            
            for put in dct["puts"]:
                data = {}
                data["maturity"] = date
                data["strike"] = put["strike"]
                data["symbol"] = put["contractSymbol"]
                data["last_price"] = put["lastPrice"]
                if "bid" in put.keys():
                    data["bid"] = put["bid"]
                else:
                    data["bid"] = None
                if "ask" in put.keys():
                    data["ask"] = put["ask"]
                else:
                    data["ask"] = None
                data["implied_volatility"] = put["impliedVolatility"]
                data["itm"] = put["inTheMoney"]
            
                options["puts"].append(data)
        
        return options
    
    def institutional_ownership(
        self,
        timestamps = False
    ) -> list:        
        try:
            data = self._stored_data["institutionOwnership"]["ownershipList"]
        except:
            raise DatasetError(f"no institutional data found for ticker {self.ticker}")
        
        data = [
            {
                "date": (entry["reportDate"]["raw"] if timestamps else dt.date.fromtimestamp(entry["reportDate"]["raw"]).isoformat()),
                "company": entry["organization"],
                "percentage": entry["pctHeld"]["raw"],
                "shares": entry["position"]["raw"],
                "value": entry["value"]["raw"]
            }
            for entry in data
        ]
        
        return data
    
    def fund_ownership(
        self,
        timestamps = False
    ) -> list:        
        try:
            data = self._stored_data["fundOwnership"]["ownershipList"]
        except:
            raise DatasetError(f"no fund ownership data found for ticker {self.ticker}")
        
        data = [
            {
                "date": (entry["reportDate"]["raw"] if timestamps else entry["reportDate"]["fmt"]),
                "fund": entry["organization"],
                "percentage": entry["pctHeld"]["raw"],
                "shares": entry["position"]["raw"],
                "value": entry["value"]["raw"]
            }
            for entry in data
        ]
        
        return data
    
    def insider_ownership(
        self,
        timestamps = False
    ) -> list:
        try:
            data = self._stored_data["insiderHolders"]["holders"]
        except:
            raise DatasetError(f"no insider holders found for ticker {self.ticker}")
        
        data = [
            {
                "date": ((entry["positionDirectDate"]["raw"] if timestamps else entry["positionDirectDate"]["fmt"])
                        if "positionDirectDate" in entry else None),
                "name": entry["name"].lower().title(),
                "position": entry["relation"],
                "shares": entry["positionDirect"]["raw"] if "positionDirect" in entry else None,
                "file": entry["url"] if len(entry["url"]) != 0 else None,
                "latest_trade": (
                    (entry["latestTransDate"]["raw"] if timestamps else entry["latestTransDate"]["fmt"]),
                    entry["transactionDescription"]
                )
            }
            for entry in data
        ]
        
        return data
    
    def ownership_breakdown(self) -> dict:        
        try:
            data = self._stored_data["majorHoldersBreakdown"]
        except:
            raise DatasetError(f"no ownership breakdown data found for ticker {self.ticker}")
        
        data["insider_ownership"] = data.pop("insidersPercentHeld")
        data["institutions_ownership"] = data.pop("institutionsPercentHeld")
        data["institutions_ownership_float"] = data.pop("institutionsFloatPercentHeld")
        data["count_institutions"] = data.pop("institutionsCount")
        
        data.pop("maxAge")
        return data
    
    def insider_trades(
        self,
        timestamps = False
    ) -> list:        
        try:
            data  = self._stored_data["insiderTransactions"]["transactions"]
        except:
            raise DatasetError(f"no insider trades found for ticker {self.ticker}")
            
        data = [
            {
                "date": (entry["startDate"]["raw"] if timestamps else entry["startDate"]["fmt"]),
                "name": entry["filerName"].lower().title(),
                "position": entry["filerRelation"],
                "file": entry["filerUrl"] if len(entry["filerUrl"]) != 0 else None,
                "shares": entry["shares"]["raw"],
                "value": entry["value"]["raw"] if ("value" in entry and entry["value"]["raw"] != 0) else None,
                "text": entry["transactionText"] if len(entry["transactionText"]) != 0 else None
            }
            for entry in data
        ]
        
        return data
    
    def esg_scores(self) -> dict:        
        try:
            data = self._stored_data["esgScores"]
        except:
            raise DatasetError(f"no esg scores found for ticker {self.ticker}")
        
        data = {
            "month": (data["ratingYear"], data["ratingMonth"]),
            "scores" : {
                "environment": data["environmentScore"],
                "social": data["socialScore"],
                "governance": data["governanceScore"],
            },
            "involvements": {
                "adult": data["adult"],
                "alcoholic": data["alcoholic"],
                "animal_testing": data["animalTesting"],
                "catholic": data["catholic"],
                "controversial_weapons": data["controversialWeapons"],
                "small_arms": data["smallArms"],
                "fur_and_leather": data["furLeather"],
                "gambling": data["gambling"],
                "gmo": data["gmo"],
                "military_contract": data["militaryContract"],
                "nuclear": data["nuclear"],
                "pesticides": data["pesticides"],
                "palm_oil": data["palmOil"],
                "coal": data["coal"],
                "tobacco": data["tobacco"],
            }
        }
        
        return data
    
    def sec_filings(
        self,
        timestamps = False
    ) -> dict:        
        try:
            data = self._stored_data["secFilings"]["filings"]
        except:
            raise DatasetError(f"no sec filings found for ticker {self.ticker}")
            
        data = [
            {
                "date_filed": int((dt.date.fromisoformat(entry["date"]) - dt.date(1970,1,1)).total_seconds()) if timestamps else entry["date"],
                "datetime_filed": entry["epochDate"] if timestamps else (dt.datetime(1970,1,1) + dt.timedelta(seconds=entry["epochDate"])).isoformat(),
                "form_type": entry["type"],
                "description": entry["title"],
                "url": entry["edgarUrl"]
            }
            for entry in data
        ]
            
        return data
    
    def fund_statistics(self) -> dict:        
        try:
            data = self._stored_data["fundProfile"]
        except:
            raise DatasetError(f"no fund holdings found for ticker {self.ticker}")
        
        data = {
            "company": data["family"],
            "style": data["categoryName"],
            "type": data["legalType"],
            "charateristics": {
                "expense_ratio" : data["feesExpensesInvestment"]["annualReportExpenseRatio"],
                "turnover": data["feesExpensesInvestment"]["annualHoldingsTurnover"],
                "aum": data["feesExpensesInvestment"]["totalNetAssets"] * 10_000
            },
            "style_url": data["styleBoxUrl"],
            "brokerages": data["brokerages"]
        }
            
        return data
    
    def holdings(self) -> dict:
        try:
            data = self._stored_data["topHoldings"]
        except:
            raise DatasetError(f"no fund holdings found for ticker {self.ticker}")
            
        data = {
            "equity_share": data["stockPosition"],
            "bond_share": data["bondPosition"],
            "holdings": [
                {
                    "ticker": entry["symbol"],
                    "name": entry["holdingName"],
                    "percent": entry["holdingPercent"]
                }
                for entry in data["holdings"]
            ],
            "equity_data": {
                "average_price/earnings": data["equityHoldings"]["priceToEarnings"],
                "average_price/book": data["equityHoldings"]["priceToBook"],
                "average_price/sales": data["equityHoldings"]["priceToSales"],
                "average_price/cashflow": data["equityHoldings"]["priceToCashflow"]
            },
            "bond_data": {
                "average_maturity": data["bondHoldings"]["maturity"] if "maturity" in data["bondHoldings"] else None,
                "average_duration": data["bondHoldings"]["duration"] if "duration" in data["bondHoldings"] else None
            },
            "bond_ratings": {
                key: entry[key] for entry in data["bondRatings"] for key in entry
            },
            "sector_weights": {
                key: entry[key] for entry in data["sectorWeightings"] for key in entry
            }
        }
            
        return data
     
    def financial_statement(
        self,
        quarterly = False,
        timestamps = False,
        merged = False
    ) -> dict:
        """
        merged : bool
            If merged is True, income, balance-sheet and cashflow data for the same period is merged into the same dictionary. 
            Otherwise the statement types act as dictionary keys, each corresponding to another dictionary that contains
            the periods as keys
            default : False
        
        """
        data = self.income_statement(quarterly=quarterly, timestamps = timestamps)        
        balance_sheet_data = self.balance_sheet(quarterly=quarterly, timestamps = timestamps)
        cashflow_data = self.cashflow_statement(quarterly=quarterly, timestamps = timestamps)
        if merged:
            for key in data:
                data[key].update(balance_sheet_data[key])
                data[key].update(cashflow_data[key])
            return data
        else:
            return {
                "income_statement": data,
                "balance_sheet": balance_sheet_data,
                "cashflow_statement": cashflow_data
            }
        
    def income_statement(
        self,
        quarterly = False,
        timestamps = False
    ) -> dict:
        data = self._get_fundamental_data(
            statement_type = "income_statement",
            quarterly = quarterly,
            timestamps = timestamps
        )
        return data
    
    def balance_sheet(
        self,
        quarterly = False,
        timestamps = False
    ) -> dict:
        data = self._get_fundamental_data(
            statement_type = "balance_sheet",
            quarterly = quarterly,
            timestamps = timestamps
        )
        return data
    
    def cashflow_statement(
        self,
        quarterly = False,
        timestamps = False
    ) -> dict:
        data = self._get_fundamental_data(
            statement_type = "cashflow_statement",
            quarterly = quarterly,
            timestamps = timestamps
        )
        return data
    
    def _get_fundamental_data(
        self,
        statement_type,
        quarterly = False,
        timestamps = False,
    ) -> dict:       
        try:
            if statement_type == "income_statement":
                if quarterly:
                    raw_data = self._stored_data["incomeStatementHistoryQuarterly"]["incomeStatementHistory"]
                else:
                    raw_data = self._stored_data["incomeStatementHistory"]["incomeStatementHistory"]
            elif statement_type == "balance_sheet":
                if quarterly:
                    raw_data = self._stored_data["balanceSheetHistoryQuarterly"]["balanceSheetStatements"]
                else:
                    raw_data = self._stored_data["balanceSheetHistory"]["balanceSheetStatements"]
            elif statement_type == "cashflow_statement":
                if quarterly:
                    raw_data = self._stored_data["cashflowStatementHistoryQuarterly"]["cashflowStatements"]
                else:
                    raw_data = self._stored_data["cashflowStatementHistory"]["cashflowStatements"]
        except:
            raise DatasetError(f"no {statement_type} data found for ticker {self.ticker}")
        
        data = {}
        for entry in raw_data:
            date = (entry["endDate"]["raw"] if timestamps else entry["endDate"]["fmt"])
            points = {CAMEL_TO_SPACE.sub(" ", key).lower():(value["raw"] if "raw" in value else np.NaN) 
                      for key,value in entry.items() 
                      if key not in ("maxAge", "endDate")}
            data[date] = points
        
        return data
    
    def _get_stored_data(self) -> dict:
        if hasattr(self, "_stored_data"):
            return self._stored_data
        
        parameters = {
            "modules": ",".join(
                (
                    'assetProfile',
                    'balanceSheetHistory',
                    'balanceSheetHistoryQuarterly',
                    'calendarEvents',
                    'cashflowStatementHistory',
                    'cashflowStatementHistoryQuarterly',
                    'defaultKeyStatistics',
                    'earnings',
                    'earningsHistory',
                    'earningsTrend',
                    "esgScores",
                    'financialData',
                    'fundOwnership',
                    'incomeStatementHistory',
                    'incomeStatementHistoryQuarterly',
                    'indexTrend',
                    'industryTrend',
                    'insiderHolders',
                    'insiderTransactions',
                    'institutionOwnership',
                    'majorDirectHolders',
                    'majorHoldersBreakdown',
                    'netSharePurchaseActivity',
                    'price',
                    'quoteType',
                    'recommendationTrend',
                    'secFilings',
                    'sectorTrend',
                    'summaryDetail',
                    'summaryProfile', 
                    'symbol',
                    'upgradeDowngradeHistory',
                    'fundProfile',
                    'topHoldings',
                    'fundPerformance'
                )
            ),
            "formatted": False
        }
        data = requests.get(
            url = self._main_url.format(self.ticker),
            params = parameters,
            headers = HEADERS
        ).json()

        if data["quoteSummary"]["error"] is not None:
            raise TickerError(f"no data found for ticker {self.ticker}")
        data = data["quoteSummary"]["result"][0]
        self._stored_data = data
        
        return self._stored_data