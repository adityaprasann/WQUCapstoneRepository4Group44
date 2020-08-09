from __future__ import (absolute_import, division, print_function,unicode_literals)
import datetime  # For datetime objects
import os.path  # To manage paths
import sys  # To find out the script name (in argv[0])
# Import the backtrader platform
import backtrader as bt
import backtrader.indicators as btind
import pandas as pd
from pandas import Series, DataFrame
import random
from copy import deepcopy
# Create a Stratey
class SMAC(bt.Strategy):
    params = {"sma": 9, "ema1": 5,"ema2": 9,
              "optim": False, "optim_variable": (9,5,9)}  # Used for optimization;
    def __init__(self):
        """Initialize the strategy"""
        self.order = None
        self.buyprice = None
        self.buycomm = None
        self.dataclose = dict()
        self.dataopen=dict()
        self.sma = dict()
        self.ema1 = dict()
        self.ema2 = dict()

        if self.params.optim:  # Use a tuple during optimization
            self.params.sma,self.params.ema1,self.params.ema2 = self.params.optim_variable  # replaced by tuple's contents

        # Can use this for sanity checks on variables
        # if self.params.ema_fast > self.params.ema_slow:
        #        raise ValueError(
        #         "A SMAC strategy cannot have the fast moving average's window be " + \
        #         "greater than the slow moving average window.")

        for d in self.getdatanames():
            # The moving averages
            self.dataclose[d] = self.getdatabyname(d).close
            self.dataopen[d] = self.getdatabyname(d).open
            self.sma[d] = btind.SimpleMovingAverage(self.getdatabyname(d),  # The symbol for the moving average
                                                       period=self.params.sma,  # Simple moving average
                                                       plotname="SMA: " + d)
            self.ema1[d] = btind.MovingAverageExponential(self.getdatabyname(d),
                                                    period=self.params.ema1,
                                                    plotname="EMA1: " + d)
            self.ema2[d] = btind.MovingAverageExponential(self.getdatabyname(d),
                                                          period=self.params.ema2,
                                                          plotname="EMA2: " + d)
        self.trade_list = []

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # Active Buy/Sell order submitted/accepted - Nothing to do
            return
        # Check if an order has been completed
        # Attention: broker could reject order if not enough cash
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log('BUY EXECUTED, Price: %.2f, Cost: %.2f, Comm %.2f' %(order.executed.price,order.executed.value,order.executed.comm))
                trade_dictionary = {"time":self.datas[0].datetime.datetime(0) ,"stock": order.data._name,"qty":order.size ,
                                 "trade": "BUY", "Entry_price": order.executed.price,
                                    }
                self.trade_list.append(trade_dictionary)
            elif order.issell():
                self.log('SELL EXECUTED, Price: %.2f, Cost: %.2f, Comm %.2f' %(order.executed.price,order.executed.value,order.executed.comm))
                trade_dictionary = {"time":self.datas[0].datetime.datetime(0),"stock": order.data._name, "qty":order.size,
                                   "trade": "SELL", "Entry_price": order.executed.price,
                                    }
                self.trade_list.append(trade_dictionary)
            self.bar_executed = len(self)
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('Order Canceled/Margin/Rejected')
            # Reset orders
        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log('TRADE PROFIT, GROSS %.2f, NET %.2f' %(trade.pnl, trade.pnlcomm))
        elif trade.justopened:
            self.log('TRADE OPENED, SIZE %2d' % trade.size)

    def log(self, txt, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        print('%s, %s' % (dt.isoformat(), txt))  # Print date and close
        # print(cerebro.broker.getvalue())
    def next(self):
        """Define what will be done in a single step, including creating and closing trades"""
        for d in self.getdatanames():  # Looping through all symbols
            pos = self.getpositionbyname(d).size or 0
            if pos == 0:  # Are we out of the market?
                if  self.dataclose[d][0]>self.dataopen[d][0]\
                        and  self.dataclose[d][-1]>self.dataopen[d][-1]  :# A buy signal
                    self.buy(data=self.getdatabyname(d),histnotify=True)

                if      self.dataopen[d][-1]>self.dataclose[d][-1] and\
                        self.ema1[d][0]<self.ema2[d][0] :  # A sell signal
                    self.sell(data=self.getdatabyname(d),histnotify=True)
            else:  # We have an open position
                if pos > 0:
                    if self.dataopen[d][0]>self.dataclose[d][0]:  # A sell signal
                        self.sell(data=self.getdatabyname(d),size =abs(pos),histnotify=True)
                if pos < 0:
                    if self.dataopen[d][0]<self.dataclose[d][0]:  # A buy signal
                        self.buy(data=self.getdatabyname(d),size =abs(pos),histnotify=True)

    def stop(self):
        print('Starting Value - %.2f' % self.broker.startingcash)
        print('Ending   Value - %.2f' % self.broker.getvalue())

class AcctValue(bt.Observer):
    def __init__(self):
        self.equity_value_list = []
    alias = ('Value',)
    lines = ('value',)
    plotinfo = {"plot": True, "subplot": True}
    def next(self):
        self.lines.value[0] = self._owner.broker.getvalue()  # Get today's account value (cash + stocks)

class AcctStats(bt.Analyzer):
    """A simple analyzer that gets the gain in the value of the account; should be self-explanatory"""
    def __init__(self):
        self.start_val = self.strategy.broker.get_value()
        self.end_val = None
    def stop(self):
        self.end_val = self.strategy.broker.get_value()
    def get_analysis(self):
        return {"start": self.start_val, "end": self.end_val,"growth": self.end_val - self.start_val,
                "return": round(((self.end_val / self.start_val)-1)*100,2)}

class PropSizer(bt.Sizer):
    """A position sizer that will buy as many stocks as necessary for a certain proportion of the portfolio
       to be committed to the position, while allowing stocks to be bought in batches (say, 100)"""
    params = {"prop": 0.02, "batch": 100}   # 2 % of Account Value in each trade
    def _getsizing(self, comminfo, cash, data, isbuy):
        """Returns the proper sizing"""
        target = self.broker.getvalue() * self.params.prop  # Ideal total value of the position
        price = data.close[0]
        shares = int(target / price)
        if shares * price > cash:
            return 0  # Not enough money for this trade
        else:
            return shares

if __name__ == '__main__':
    start = datetime.datetime(2017, 8, 1)
    end = datetime.datetime(2020, 4, 30)
    is_first = True
    # Create a cerebro entity
    cerebro = bt.Cerebro(stdstats=False,optreturn=False)
    symbols = ['adaniports_15min.csv', 'asianpaint_15min.csv', 'axisbank_15min.csv', 'bajajfinsv_15min.csv', 'bajaj_auto_15min.csv',
               'bajfinance_15min.csv', 'bhartiartl_15min.csv', 'bpcl_15min.csv', 'britannia_15min.csv', 'cipla_15min.csv',
               'coalindia_15min.csv', 'drreddy_15min.csv', 'eichermot_15min.csv', 'gail_15min.csv', 'grasim_15min.csv',
               'hcltech_15min.csv', 'hdfcbank_15min.csv', 'hdfc_15min.csv', 'heromotoco_15min.csv', 'hindalco_15min.csv',
               'hindunilvr_15min.csv', 'icicibank_15min.csv', 'indusindbk_15min.csv', 'infratel_15min.csv', 'infy_15min.csv',
               'ioc_15min.csv', 'itc_15min.csv', 'jswsteel_15min.csv', 'kotakbank_15min.csv', 'lt_15min.csv', 'maruti_15min.csv',
               'mm_15min.csv', 'nestleind_15min.csv', 'ntpc_15min.csv', 'ongc_15min.csv', 'powergrid_15min.csv', 'reliance_15min.csv',
               'sbin_15min.csv', 'sunpharma_15min.csv', 'tatamotors_15min.csv', 'tatasteel_15min.csv', 'tcs_15min.csv', 'techm_15min.csv',
               'titan_15min.csv', 'ultracemco_15min.csv', 'upl_15min.csv', 'vedl_15min.csv', 'wipro_15min.csv', 'zeel_15min.csv']
    plot_symbols = symbols
    for s in symbols:
        data = bt.feeds.GenericCSVData(dataname=s,
                                       fromdate=start,todate=end,
                                       datetime=0, open=1, high=2, low=3, close=4,
                                       volume=5, openinterest=-1, timeframe=bt.TimeFrame.Ticks,
                                       dtformat="%Y-%m-%d %H:%M:%S",
                                       # tmformat='%H:%M',     sessionstart=sessionstart
                                       )
        if s in plot_symbols:
            if is_first:
                data_main_plot = data
                is_first = False
            else:
                data.plotinfo.plotmaster = data_main_plot
        else:
            data.plotinfo.plot = False
        cerebro.adddata(data)  # Give the data to cerebro
    # Generate random combinations of fast and slow window lengths to test
    windowset = set()
    l_array = [3, 5]
    s_array = [5, 9, 14]
    for l in l_array:
        for s in s_array:
                if s > l:  # Cannot have the fast moving average have a longer window than the slow, so swap
                    l, s = s, l
                    windowset.add((5, l, s))
                elif l == s:  # Cannot be equal, so do nothing, discarding results
                    pass
                else:
                    windowset.add((5, l, s))
    windows = list(windowset)
    print("no of run is ", len(windows), windows)
    cerebro.addobserver(AcctValue)
    cerebro.addanalyzer(AcctStats)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe_ratio')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='SQN')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='TradeAnalyzer')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='DrawDown')
    cerebro.addanalyzer(bt.analyzers.Transactions, _name='Transactions')

    #cerebro.addstrategy(SMAC)
    cerebro.optstrategy(SMAC, optim=True, optim_variable=windows)
    #cerebro.addsizer(bt.sizers.FixedSize, stake=10)  # Add a FixedSize sizer according to the stake
    cerebro.addsizer(PropSizer)   # Add a Variable sizer
    # Set our desired cash start
    cerebro.broker.setcash(2500000.0)
    # Set the commission
    cerebro.broker.setcommission(commission=0.0001)
    # Print out the starting conditions
    #print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
    # Run over everything
    res = cerebro.run()
    list1=[]
    for strat in res:
        sharpe = strat[0].analyzers.sharpe_ratio.get_analysis()
        sq = strat[0].analyzers.SQN.get_analysis()
        ta = strat[0].analyzers.TradeAnalyzer.get_analysis()
        retur_perc = strat[0].analyzers.acctstats.get_analysis()
        drawdown = strat[0].analyzers.DrawDown.get_analysis()
        transactions1 = strat[0].analyzers.Transactions.get_analysis()   # its ordered dictionary
        # this is a way of creating tradesheet, by adding analyzer class Transactions
        tradesheet_list = []
        for key in transactions1.keys():
            transactions_dict = {"Stock": transactions1[key][0][3], "Entry_time": key,"Entry_Price": transactions1[key][0][1],
                                 "qty": transactions1[key][0][0], "value": transactions1[key][0][4]}
            tradesheet_list.append(transactions_dict)
        name_of_run = '_'.join([str(x) for x in strat[0].params.optim_variable])  #to convert from tuple of int to list of string
        pd.DataFrame(tradesheet_list).to_csv("1_"+name_of_run+"_tradesheet_combined.csv",index=False)
        #print(ta.keys())  # there are many stats in this, nested dictionaries
        stats_summary = {"run_name": name_of_run,"end": str(retur_perc['end']),"growth": str(retur_perc['growth']),
                            "% return": round(retur_perc['return'],2),"sharpe": round(sharpe['sharperatio'],2),"SQN":round(sq["sqn"],2),
                         "Trades":str(sq["trades"]) , "open_trades": str(ta['total']['open']) ,"average_pnl": round(ta['pnl']['net']['average'],2) ,
                          "won_trades": str(ta['won']['total']) , "loss_trades": str(ta['lost']['total']) ,
                         "long_trades": str(ta['long']['total']) ,"short_trades": str(ta['short']['total']) ,
                         "max_DD": round( drawdown['max']['moneydown'],2)
                         }
        list1.append(stats_summary)

    summary = pd.DataFrame(list1)
    summary.sort_values(by=['SQN'],ascending=False,inplace=True)  # Sort the result by SQN, highest SQN at top
    summary.to_csv("1_summary.csv", index=False)  # summary of all runs
    # Plot the result
    cerebro.plot(iplot=True, volume=False)