"""Classify Anish's followed accounts. Categories:
memecoin_caller  - posts/trades Solana/pump.fun memecoins, calls, trenches
crypto_general   - crypto news, VC, L1/L2, exchanges, wallets, macro-crypto traders, NFT/ENS, AI-agent tokens
not_crypto       - everything else
Evidence = bio keywords + (where noted) posts seen in data/probe*.txt or third-party caller boards."""
import json, csv, re
d = json.load(open('data/following_raw.json'))['data']

MEME = {
 'orangie': 'Known Solana memecoin trader/streamer; bio content creator',
 'blknoiz06': 'Ansem; posts about pump.fun callouts/rewards (probe1); Kolscan-listed wallet',
 'notthreadguy': 'Memecoin streamer, works on @fomo (memecoin app)',
 'dr_crypto_calls': 'Bio "Early plays, alpha"; on pumpbubble callers board (52% 2x, 63 calls/7d)',
 'SolanaRockets': 'Bio: free telegram to track my trades (Solana)',
 'SolLynx_': 'Bio "manifesting 1000x"',
 'TopTrendingSol': 'Bio #SolanaMemecoin #100x',
 'MemeRetire': 'Bio "Investigating memecoins"; pumpbubble KOL #8 (thedetective)',
 'Legend_Legolas': 'Bio "Alpha Hunter"',
 'Lowskii': 'Bio "trader of internet coins"',
 'DamnGoodCoins': 'Bio "paid off mortgage with memecoins"',
 'The__Solstice': 'Bio "Head degen @flywheelcash", fomo referral; pumpbubble KOL #50',
 'NachSOL': 'Bio generational wealth, @PioneerFNF (Solana)',
 'metaversejoji': 'Bio @lairfnf @dabalfnf (Solana memecoin groups)',
 'brandonsalim': 'Bio "tradoor", trading app referral',
 'ecca': 'Solana memecoin trader (bio "retar/dio")',
 'spunosounds': 'Solana memecoin trader (name/known, bio unclear)',
 'WolverCrypto': 'Bio "Low Cap Gems"',
 'based16z': 'Memecoin trader (known; bio joke)',
 'gammichan': 'Bio "Trader, angel investor"; memecoin-trader circle',
 'dohertyjackk': 'Memecoin trader (empty bio; low confidence)',
 'ohbrox': 'Memecoin trader (bio unclear; low confidence)',
 'd_gilz': 'Trader, @skewtrade (low confidence memecoin)',
 'Indegenuity': 'Bio "Fighting nerds in the trenches"',
 'FloweyQuant': 'Bio "24/7 in the trenches", AI trading bot',
 'DeFi_Hanzo': 'Bio "Made 90% of my money in crypto, not by being a KOL"',
 'mindbath': 'Bio pins a pump CA ($ZEN) - token promoter',
 'matt_levAIne': 'Bio pins a pump CA - token account',
 'tate_terminal': 'Bio pins a CA - token/AI agent account',
 'truth_terminal': 'AI agent behind $GOAT memecoin narrative',
 'labubufans': 'Bio: fan token on Solana',
 'CoinHunterAIBot': 'Bio: AI looking for memecoins',
 'iAmMoney00': 'Bio "now I gamble for fun"',
 'Cryptobigm': 'Bio "Buy the dip, sell the rip"',
 'CryptobigM': 'Bio "Buy the dip, sell the rip"',
 'GalleonCrypto': 'Bio "All things crypto" (low confidence)',
 'VoodooFungi': 'Bio shills $ZAUTH $CHOP',
 'notfrydoteth': 'Bio "market participant" (low confidence)',
 'Dyor_0x': 'Bio "Trades and Predictions"',
 'urboiMJ': 'Bio NFA/DYOR (low confidence)',
 '0xZyaf': 'Bio "Printing magic internet money"; posts "callouts", promises "next 100x" (probe1)',
 'mikadontlouz': 'Bio "trade the news"',
 'MarzellCrypto': 'Content creator, AI trading tools',
 'Aaronbennett': 'Bio "Crypto. Meme Poster."',
 'thejbullmarket': 'Bio shills $JEANPHIL $PANGEA',
 'unknowDLT': 'Bio "Not financial advice." (low confidence)',
 'Zssbeker__': 'Bio NEO Tokyo game tweets/NFA (possible impersonator of @ZssBecker)',
 '_0xTrsk': 'Bio "years in the shitcoin trenches", now perps',
 'seshomaruB16': 'Bio "Believe in something" (Believe app slogan; low confidence)',
 'uyye_yeah': 'Bio "cycle mems"',
 'jeetlaggedETH': 'Empty bio; name suggests trench trader (low confidence)',
 'GaryCla16787498': 'Bio "asymmetric opportunities", crypto investor',
 'notbad': 'Low confidence trench trader',
 'XESAS01': 'Low confidence trench trader (bio "keep clicking")',
 'amonyx': 'Low confidence',
 'Hasbulla': 'Celebrity linked to Hasbulla memecoins',
 'HasbullaHive': 'Hasbulla fan page (memecoin-adjacent)',
 'ishowspeedsui': 'Impersonation/meme-token style account (name)',
 'kanyestreams1': 'Unclear; low confidence',
}
GEN = {
 'GuoShenCN7':'AI agents onchain','Cryptoking':'Crypto since 2017','AlexMasonCrypto':'Crypto wealth','0xkenzolee':'Stocks+crypto','NFTMillionaire':'NFT','leaf_swan':'NFT class of 21','UnknownCo123':'NFT art TG','Sendrock':'NFT @SpiritDAO','pixelord':'web3 opensea artist','thousandbtc':'BTC name','CryptoWendyO':'Blockchain news','worldlibertyfi':'WLFI','RitOnchain':'onchain quant','CryptoGorilla':'Crypto videos','Sheldino_D':'Crypto chartist','lookonchain':'On-chain smart money tracker','thedefiedge':'Crypto research','Route2FI':'Narrative trader','kyledoops':'Swing trader','fiction_finance':'Crypto/stocks','DrProfitCrypto':'BTC trader','CryptoTony__':'Crypto','cryptomanran':'Crypto Banter','milesdeutscher':'Crypto/AI','Neura_Web3_AI':'Web3 AI','CryptoTeca__':'Crypto researcher','0xIamBK':'Blockchain','0xNonceSense':'Macro & crypto onchain','Astra__Nova':'$RVV token project','ShytoshiKusama':'Shiba Inu lead','blorm_':'Onchain AI','vvaifudotfun':'AI agent token launchpad','ayoubedeth':'Ex-CTO crypto project','aixbt_agent':'Crypto intel AI agent','datafdn':'Crypto infra (Story)','OxZerePy':'AI agent framework (crypto)','phantom':'Solana wallet','BinanceWallet':'Binance wallet','binance':'Exchange','BillyM2k':'Dogecoin creator','ZssBecker':'Crypto','0xNickolas':'DAO','0xRecrent':'0x handle (low confidence)','0xPuzz':'Web3','crypto_bull':'Crypto advisor','freakyfawi':'Perps trader','11_NFTS':'Blockchain','Web3Quant':'Crypto long/short','WatcherGuru':'Crypto news','address_eth':'ENS','armyrock_eth':'ENS','EnsSalesBot':'ENS bot','ENSTradingPost':'ENS','mrpunkdoteth':'NFT/crypto','player1':'Polymarket trader','hanjiahnn':'BTC/ETH trader','cryptorover':'Bitcoin YouTuber','VitalikButerin':'Ethereum','DonWedge':'Growth @asendnow (crypto)','fundedtrusts':'Crypto (low confidence)','cheick_yn':'Unknown (low confidence)','Chevo_krypto':'Krypto name','galactus_10':'Unknown (low confidence)','cloudz_e':'Unknown','CEO_KICKS':'Unknown','benrichatl':'Unknown','ga74_5':'Unknown','MNxSWISHER':'Unknown','0xROAS':'Ads (not crypto?)','bio7ss':'crypto enthusiast','Kalshi':'Prediction market','hyardimcioglu':'Anti-central bank (BTC)','com_domains':'Domains','tintsion':'Unknown','techtrends_tech':'Tech','LYSIOS':'AI', 'cb_doge':'Elon/DOGE fan news','reb40':'Unknown','ianrocksx':'Unknown',
}
# Accounts in GEN with low confidence that are actually probably not crypto get reclassified below
NOT_OVERRIDE = {'0xROAS','techtrends_tech','LYSIOS','reb40','ianrocksx','MNxSWISHER','CEO_KICKS','tintsion','cloudz_e','benrichatl','ga74_5','galactus_10','cheick_yn','cb_doge','com_domains'}
rows=[]
for u in d:
    h=u['username']; bio=re.sub(r'\s+',' ',u.get('description',''))
    if h in MEME: cat,ev='memecoin_caller',MEME[h]
    elif h in GEN and h not in NOT_OVERRIDE: cat,ev='crypto_general',GEN[h]
    else:
        cat,ev='not_crypto','bio: '+bio[:80]
        if h in NOT_OVERRIDE: ev='unclear/empty bio, not crypto by bio (unverified): '+bio[:60]
    rows.append({'handle':h,'name':u['name'],'followers':u['public_metrics']['followers_count'],'category':cat,'evidence':ev,'bio':bio[:200],'user_id':u['id']})
with open('following_crypto.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
from collections import Counter
print(Counter(r['category'] for r in rows))
missing=[h for h in list(MEME)+list(GEN) if h not in {r['handle'] for r in rows}]
print('missing',missing)
