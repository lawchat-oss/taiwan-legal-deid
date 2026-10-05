"""針對已知弱點的擴增（全標註、全虛構人名）：
3. 英文：品牌／App／英文地址／信尾敬語＝不是人名；英文人名＝要遮。
4. 英文片語（病歷段落標題、職稱）與「人名＋店名」（林家牛肉麵、阿宗麵線式）＝不是人名。
5. 公眾人物（保留）對照同姓一般人（要遮）；店名裡的「姓＋稱謂」不是人、本人是人；句首只寫名字；護照式英文姓名。
1. 路名／區名：內政部全國路名資料（政府資料開放授權）放進常見句型；人名＝要遮，路名區名裡的候選＝不是人名（鄭成功路、林森北路、楊梅區）。
2. 「即＋職稱」：被告即法官某某、證人即書記官某某 → 仍是當事人（要遮）；被告某某律師（律師本人是被告）→ 要遮。
   對照組：本件經法官某某審理、選任辯護人某某律師 → 保留。
6. 法律文件的日期（事件日保留、出生日要遮）。7–10（v11）：上市櫃公司當事人／雇主 vs 順帶提到、英文暱稱、日本人名、私人 vs 機構電話。
   標註位置沒有一模一樣候選的文件整份丟掉（_uncovered；只有保留機構沒候選的話，拿掉那個標註就好）。
用法：python -m taiwan_legal_deid.data_augment → data/train/aug_docs.jsonl
"""
from __future__ import annotations

import collections, csv, glob, json, os, random

from .names import TRAIN_WILD, sample_name as _sample_name

sample_name = lambda rng, **k: _sample_name(rng, wild=TRAIN_WILD, **k)  # 訓練用假名：含罕見姓、像一般詞的名字

D = os.path.join(os.path.dirname(__file__), "..", "data")
PARTY = ("被告", "告訴人", "證人", "上訴人", "被上訴人", "原告", "聲請人", "相對人", "被害人", "抗告人")
TITLES = ("法官", "書記官", "檢察官", "律師", "司法事務官", "法官助理", "通譯", "前書記官", "退休法官", "前檢察官", "警員", "調查官")
ROAD_TPL = ("{p}駕車行經{road}時遭警攔查。", "該處位於{road}與{road2}口，{p}當時在場。", "{p}居住於{city}{dist}{road}{n}號。",
            "{p}於{road}附近遭{q}毆打。", "{p}自{dist}前往{road2}途中發生車禍。", "{p}在{road}開設小吃店。",
            "依{p}所述，其當日行經{dist}{road}。", "{p}與{q}相約於{road}見面。", "事發地點為{city}{dist}{road}與{road2}交岔路口。")
JI_TPL = ("{role}即{title}{p}{tail}", "{role}{p}即{title}{tail}", "{role}{p}律師{tail}")
KEEP_TPL = ("本件經{title2}{k}審理。", "選任辯護人{k}律師到庭。", "本案經檢察官{k}提起公訴，{role}{p}否認犯行。", "書記官{k}記錄。")
BRANDS = ("Netflix", "Google", "Apple", "Facebook", "Instagram", "YouTube", "Uber", "Excel", "Word", "Teams", "Zoom", "Gmail", "Outlook",
          "Dropbox", "Shopee", "Momo", "Yahoo", "Spotify", "Disney", "Costco", "Ikea", "Starbucks", "Toyota", "Honda", "Microsoft",
          "Amazon", "Canva", "Notion", "Slack", "Telegram", "Android", "Windows", "Chrome", "Safari", "Line Pay", "Foodpanda", "Uber Eats")
EN_ROADS = ("Roosevelt", "Zhongshan", "Minsheng", "Xinyi", "Heping", "Fuxing", "Dunhua", "Keelung", "Jianguo", "Nanjing", "Zhongxiao",
            "Chang'an", "Bade", "Wenhua", "Zhonghua", "Minzu", "Ziyou", "Daan", "Songjiang", "Guangfu")
EN_DISTS = ("Da'an", "Xinyi", "Zhongzheng", "Banqiao", "Xinzhuang", "Sanchong", "Zhonghe", "Neihu", "Shilin", "Beitou", "Wanhua",
            "Songshan", "Xitun", "Lingya", "Annan", "Taoyuan", "Zhubei", "East", "West", "North")
EN_CITIES = ("Taipei City", "New Taipei City", "Taichung City", "Kaohsiung City", "Tainan City", "Taoyuan City", "Hsinchu City", "Keelung City")
CLOSINGS = ("Best Regards", "Kind Regards", "Sincerely", "Thanks & Regards", "Best wishes", "Cheers", "Warm regards")
EN_FIRST = ("Kevin", "Amy", "Ivy", "Jason", "Grace", "Eric", "Vivian", "Andy", "Cindy", "Tony", "Sandy", "Michael", "Jessica", "Peter",
            "Wendy", "Allen", "Iris", "Ken", "Joyce", "Ryan", "Tina", "Leo", "Zoe", "Mia")
EN_LAST = ("Lin", "Chen", "Wang", "Huang", "Chang", "Lee", "Wu", "Liu", "Tsai", "Yang", "Hsu", "Cheng", "Smith", "Brown", "Tanaka")
ROMAN_NAMES = ("Lin Chia-Hao", "Chen Mei-Ling", "Wang Hsiao-Ming", "Lee Ting-Yu", "Huang Yu-Ting", "Chang Wei-Lun", "Wu Pei-Shan",
               "Tsai Cheng-Han", "Liu Yi-Chen", "Hsu Kuan-Yu")
EN_TPL = ("請用{plat}傳給{p}，順便開{plat2}確認。", "{p}的{plat}帳號被盜了。", "{closing},\n{p}", "寄送地址：{addr}，收件人 {p}。",
          "Hi {q}，{plat}的會議連結在這。", "我昨天用{plat}跟{q}視訊。", "公司地址：{addr}\n聯絡窗口：{p}", "{closing},\n{plat}客服中心",
          "請在{plat}搜尋{plat2}的官方帳號。", "{p} 先生您好，您在{plat}的訂單已出貨。", "麻煩把{plat}的報表寄給 {q}。")
EN_PHRASES = ("Best Regards", "Kind Regards", "Chief Complaint", "Present Illness", "Past Medical History", "Hospital Course",
              "Physical Examination", "Family History", "Team Building", "Project Manager", "Customer Service", "Thank You",
              "Happy Birthday", "Merry Christmas", "Good Morning", "Annual Report", "Meeting Notes", "Action Items", "Due Date",
              "Sales Report", "Human Resources", "General Manager", "Account Manager", "Product Owner", "User Guide", "Sold Out",
              "Free Shipping", "Order Number", "Tracking Number", "Discharge Summary", "Final Diagnosis", "Sign Up", "Log In")
BIZ_SUFFIX = ("牛肉麵", "麵線", "豆花", "牛排", "麵包店", "餐廳", "診所", "牙醫診所", "商行", "工作室", "便當", "小吃店", "鹹酥雞", "飲料店",
              "茶行", "早餐店", "水餃館", "冰店", "滷味", "藥局")
FOODS = ("牛肉麵", "豆漿", "麵線", "米糕", "肉圓", "滷肉飯", "鍋貼", "水煎包", "豆花", "雞排", "粥", "燒臘")
NEG_TPL = ("昨天去吃{biz}，排了半小時。", "{biz}今天公休，改天再去。", "我在{biz}買了晚餐，{p}說很好吃。", "推薦{biz}，老闆人很好。",
           "{phrase}：病人主訴胸悶兩天。", "【{phrase}】\n請於週五前回覆。", "{phrase}\n{p}", "下午的{phrase}在三樓會議室。",
           "{phrase}：{phrase2}已更新。", "Hi {q}，{phrase}的檔案已上傳。", "{biz}的外送員{p}把餐點送錯了。")
PUBLIC = ("賴清德", "蔡英文", "馬英九", "陳水扁", "李登輝", "蔣中正", "蔣經國", "孫中山", "柯文哲", "侯友宜", "蔣萬安", "黃國昌", "韓國瑜",
          "朱立倫", "卓榮泰", "陳建仁", "蕭美琴", "張忠謀", "郭台銘", "黃仁勳", "魏哲家", "施振榮", "王雪紅", "林百里", "周杰倫", "蔡依林",
          "張惠妹", "林志玲", "周星馳", "劉德華", "伍佰", "蕭敬騰", "林俊傑", "王力宏", "李安", "侯孝賢", "楊德昌", "金城武", "舒淇",
          "桂綸鎂", "吳念真", "戴資穎", "林昀儒", "郭婞淳", "王建民", "陳偉殷", "林書豪", "曾雅妮", "盧彥勳", "謝淑薇", "李洋", "王齊麟",
          "楊勇緯", "唐鳳", "吳寶春", "鄭成功", "詹天佑", "蔣渭水", "林獻堂", "賴和", "白先勇", "余光中", "席慕蓉", "孔子", "孟子", "諸葛亮",
          "曹操", "劉備", "秦始皇", "李白", "杜甫", "蘇軾", "王羲之", "岳飛", "文天祥", "林則徐", "鄭和", "馬偕", "川普", "拜登", "習近平",
          "普丁", "大谷翔平", "梅西", "愛因斯坦", "牛頓", "達文西", "賈伯斯", "馬斯克", "比爾蓋茲", "林懷民", "江蕙", "鄧麗君", "費玉清",
          "陶晶瑩", "吳宗憲", "張學友", "梁朝偉", "成龍", "彭于晏", "許光漢", "林依晨", "陳妍希", "宋芸樺", "謝金燕", "李國修", "張清芳")
KIN = ("媽媽", "阿姨", "師傅", "董", "伯", "嬸", "阿嬤", "哥", "姐", "爸", "叔", "老闆")
EVENTS = ("論壇", "記者會", "頒獎典禮", "國慶典禮", "演唱會", "簽書會", "比賽", "開幕式", "座談會")
PUB_TPL = ("{fig}今天出席{event}，我們公司的{p}也在台下。", "{p}說他從小最崇拜{fig}。", "新聞報導{fig}在{event}的發言，{p}在群組轉傳。",
           "{fig}開的{fig_shop}{shop}又推新品，{p}排了一小時才買到。", "{fig}的{event}門票秒殺，{p}一張都沒搶到。",
           "{sur}{kin}{food}今天公休，{sur_p}{kin}本人說明天照常營業。", "昨天去{sur}{kin}{food}，{q}說很好吃。",
           "{q}說她下午會晚點到，{q}的媽媽會先來。", "，{q}已經把報告改好了，{p}再幫忙看一次。", "{q}跟{p}今天都請假。",
           "旅客姓名：{pp}　航班：BR{n}　請於起飛前完成登機。", "申請人 {pp} 之文件業經核准。", "我姓{sur_p}，跟{fig}沒有關係。")
TAILS = ("涉犯背信罪，經檢察官提起公訴。", "於偵查中否認犯行。", "到庭證稱其未經手該卷宗。", "不服原審判決提起上訴。",
         "坦承收受款項。", "指稱遭被告公然侮辱。", "於審理時否認犯行。")


SPAN_KEYS = {"p": "MASK", "q": "MASK", "pp": "MASK", "sur_p": "MASK", "k": "KEEP", "fig": "KEEP",  # 其他欄位（店名裡的 sur、fig_shop）不標
             "event": ("KEEP", "pii", "DATE"), "event2": ("KEEP", "pii", "DATE"), "birth": ("MASK", "pii", "BIRTH"),
             "nick": "MASK", "jp": "MASK", "jp2": "MASK", "jp_sur": "MASK", "land": ("MASK", "pii", "TEL"), "mobile": ("MASK", "pii", "TEL"),
             "full": ("MASK", "org", "ORG"), "short": ("MASK", "org", "ORG"), "short_k": ("KEEP", "org", "ORGK"), "inc": ("KEEP", "org", "ORGK"),
             "pp2": "MASK", "brand": ("MASK", "org", "ORG"), "brand_b": ("MASK", "org", "ORG"), "brand_k": ("KEEP", "org", "ORGK"),
             "plat": ("KEEP", "org", "ORGK"), "plat2": ("KEEP", "org", "ORGK")}  # 英文模板裡順帶用到的平台（Google、Zoom）＝保留
# 11. 移工、外配的護照式姓名（全大寫、空白隔開）
PASS_NAMES = {"vn": (("NGUYEN", "TRAN", "LE", "PHAM", "HOANG", "HUYNH", "PHAN", "VU", "VO", "DANG", "BUI", "DO", "NGO", "DUONG"),
                     ("VAN", "THI", "DUC", "MINH", "NGOC", "HUU"), ("HUNG", "MAI", "NAM", "HOA", "LAN", "ANH", "TUAN", "LINH", "HAI", "PHUONG", "TRANG")),
              "id": (("SITI", "DEWI", "SRI", "NUR", "WULAN", "AGUS", "BUDI", "RINA", "INDAH", "PUTRI", "EKA", "YULI"),
                     ("AISYAH", "LESTARI", "WAHYUNI", "HIDAYAH", "PERTIWI", "SETIAWAN", "SANTOSO", "RAHAYU", "SARI", "WATI", "KURNIAWAN")),
              "th": (("SOMCHAI", "SUPAPORN", "ANAN", "PORNTIP", "KITTI", "NARONG", "SIRIPORN"), ("SRISUK", "KAEWMANEE", "THONGDEE", "CHAIYAPORN", "BOONMA")),
              "ph": (("MARIA", "JOSE", "ANALYN", "JOVELYN", "MARIBEL", "ROSALIE", "JUNREY"), ("SANTOS", "REYES", "GARCIA", "MENDOZA", "BAUTISTA", "AQUINO"))}
PASS_TPL = ("外籍看護工{pp2}（印尼籍）於{n}年前來臺照顧{p}。", "移工{pp2}向勞工局申訴雇主{p}扣留其護照。", "被告{p}僱用越南籍移工{pp2}，未依法為其投保勞工保險。",
            "外籍配偶{pp2}（越南籍）與{p}於{n}年前結婚，育有一子。", "{pp2}：老闆說這個月薪水晚點發。", "受看護人{p}之家屬指稱{pp2}擅自離開。",
            "證人{pp2}（菲律賓籍）經通譯傳譯後證稱其未見到{p}。", "仲介公司將{pp2}轉介至{p}家中工作。")
# 12. 連鎖、國營、大品牌（org_candidates.BRANDS）：當雇主、當事人＝要換；順帶提到（繳費、吃飯、搭車、門號）＝保留
BRAND_PARTY = ("我在{brand}上班{n}年了，{brand}主管一直要我加班卻不給加班費。", "聲請人{p}任職於{brand_b}，遭{brand}以業績不佳為由解僱。",
               "被告{brand}未依約退費，原告{p}爰依消費者保護法請求返還。", "{p}在{brand_b}擔任店長，{brand}積欠加班費{amt}元。",
               "原告{p}於{brand_b}購買之商品有瑕疵，{brand}拒絕退貨。", "{p}自{brand}離職後，{brand}拒絕開立離職證明書。")
BRAND_INC = ("{p}到{brand_k}繳完電話費才去上班。", "{p}在{brand_k}買了晚餐就回家了。", "{p}搭{brand_k}回台北開庭。", "{p}的手機門號是{brand_k}的。",
             "{p}約對方在{brand_k}門口見面。", "收據是{p}在{brand_k}列印的。")
BRANCH_NAMES = ("文心", "鳳山青年", "公館直營", "板橋文化", "台中中港", "天母", "嘉義區", "信義新天地", "中壢", "新竹站前")
# 7. 上市櫃公司（taiwan_legal_deid.companies）：當事人、雇主＝要換（全名、簡稱、下稱都是）；順帶提到（開戶、繳費、股票、新聞）＝保留
CO_PARTY = ("原告{p}與被告{full}（下稱{short}）間請求給付資遣費事件，{short}應給付原告新臺幣{amt}元。",
            "上訴人{full}與被上訴人{p}間損害賠償事件，{short}主張已依約給付。",
            "{p}自{n}年前起任職於{full}，嗣遭{short}違法解僱，爰請求給付資遣費。",
            "我在{short}上班{n}年了，{short}說要資遣我，請問律師該怎麼辦？", "被告{short}未依約退還押金{amt}元，原告{p}爰依民法第179條請求返還。",
            "{p}為{short}員工，於工作中受傷，{short}拒絕給付職業災害補償。", "債務人{full}積欠債權人{p}貨款{amt}元，經{p}催告仍未清償。",
            "{p}與{full}簽訂勞動契約，約定由{short}按月給付薪資{amt}元。", "原告{p}主張其向被告{full}購買預售屋，惟{short}遲延交屋。",
            "{p}受僱於{short}，離職後{short}要求其賠償違約金{amt}元。", "聲請人{p}與相對人{full}間勞資爭議調解事件，{short}代理人到場。",
            "{p}向{short}申訴遭主管霸凌，{short}人資部門迄未處理。")
CO_INC = ("{p}在{inc}開戶，每月薪資轉入該帳戶。", "{p}到{inc}繳費後，把收據拍照傳給律師。", "新聞報導{short_k}今年營收創新高，{p}在群組轉傳這則新聞。",
          "{p}手上有{short_k}的股票，打算明年賣掉。", "{p}用{inc}下單，收到商品後發現有瑕疵。", "{short_k}是國內知名企業，與本件爭議無關。",
          "{p}的手機門號是在{inc}申辦的，帳單地址已變更。")
INCIDENTAL = ("玉山銀行", "國泰世華銀行", "台新銀行", "中國信託商業銀行", "第一銀行", "合作金庫銀行", "台北富邦銀行", "兆豐銀行", "華南銀行", "中華郵政",
              "7-ELEVEN", "全家便利商店", "萊爾富", "全聯福利中心", "家樂福", "好市多", "蝦皮購物", "momo購物網", "PChome", "Uber Eats", "foodpanda",
              "LINE Pay", "街口支付", "中華電信", "台灣大哥大", "遠傳電信")
# 8. 英文暱稱（LINE 聯絡人、對話）：全大寫、首字大寫都有；同一句放 LINE、ATM、PDF 這類縮寫（不是人）
NICKS = EN_FIRST + ("Amie", "Jojo", "Mimi", "Lulu", "Kiki", "Yoyo", "Bobo", "Coco", "Momo", "Nana", "Tina", "Lily", "Ruby", "Vicky", "Penny",
                    "Wendy", "Ken", "Max", "Leo", "Ray")
NICK_TPL = ("{nick} {mobile}", "聯絡人：{nick}　電話：{mobile}", "{nick}：好，明天下午三點在公司樓下見。", "{nick}：我已經用LINE把PDF傳給你了。",
            "我跟{nick}約在KTV，{nick}說會晚一點到。", "請把ATM轉帳收據傳給{nick}，{nick}會再跟會計確認。", "{nick} 說那個APP的VIP會員費不退。",
            "{nick}：OK，USB 我明天帶過去。", "傳給{nick}的訊息顯示已讀，{nick}一直沒回。", "{nick}（{mobile}）是我的前同事，可以作證。",
            "{p}跟{nick}都在群組裡，{nick}說LV包是{p}送的。")
# 9. 日本人名（日文契約、跨國案件）：姓 2～4 字（含々），姓名之間可能有空白；姓＋部長／様／さん
JP_GIVEN = ("健太", "一郎", "翔太", "大輔", "拓也", "直樹", "和也", "健一", "誠", "浩", "剛", "隆", "雅人", "博之", "秀樹", "達也", "健二", "修", "正樹", "良徳",
            "美和", "由美子", "恵子", "陽子", "真理子", "愛", "優子", "明美", "裕子", "直美", "智子", "美穂", "香織", "麻衣", "彩", "翔", "蓮", "悠真", "結衣", "葵",
            "ゆかり", "さくら", "あゆみ", "ひなた", "みゆき", "まりこ", "たかし", "ひろし", "柚葉", "凜", "菜々子", "紘一", "慎也", "航")
JP_TPL = ("甲方：{p}\n乙方：{jp}（日本國籍）\n雙方同意依本契約條款履行。", "連帶保證人{jp}同意就本契約負連帶保證責任。",
          "{jp_sur}部長於會議中表示，貨款將於下月支付。", "本契約由{jp}代表乙方簽署，{jp_sur}様確認無誤。",
          "{p}與{jp}於東京簽訂合作備忘錄，{jp_sur}さん負責後續聯繫。", "受任人{k}律師代理委任人{jp}處理在臺不動產事宜。",
          "{jp}（{jp2}之配偶）主張其對系爭房屋有居住權。")
# 10. 電話：私人（住家、手機、「打這支聯絡我」）要遮；公司總機、客服、機關、事務所的電話不是個資（不標＝不是）
TEL_TPL = ("住家電話：{land}", "有事請打我家裡電話{land}，白天打手機{mobile}。", "電話{land}聯絡我，晚上九點前都可以。",
           "{p}的手機是{mobile}，住家電話{land}。", "公司總機{land_x}，請轉{p}分機。", "客服專線0800-{d3}-{d3b}，服務時間週一至週五。",
           "本院電話（0{a}）{d8}，承辦股別：{gu}股。", "{k}律師事務所電話{land_x}，傳真{land_x2}。", "如有疑問請洽{dept}，電話{land_x}。",
           "{p}留下的聯絡電話為{mobile}，另提供公司電話{land_x}。")
DEPTS = ("臺北市政府勞動局", "消費者服務中心", "本公司人資部", "新北市政府法制局", "本會秘書處", "區公所社會課")


def _land(rng):
    a = rng.choice(("02", "03", "04", "05", "06", "07", "08", "037", "049", "089"))
    body = f"{rng.randint(2, 8)}{rng.randint(100, 999) if a == '02' else rng.randint(10, 99)}-{rng.randint(1000, 9999)}"
    return rng.choice((f"({a}){body}", f"{a}-{body}", f"（{a}）{body}", f"+886-{a[1:]}-{body}"))


def _mobile(rng):
    return rng.choice((f"09{rng.randint(10, 99)}-{rng.randint(100, 999)}-{rng.randint(100, 999)}", f"09{rng.randint(10000000, 99999999)}"))


def _uncovered(text, spans):
    """沒有一模一樣候選的標註：留著的話，重疊的候選全被當成「不是」，等於教模型別遮。"""
    from .candidates import candidates
    from .labels import GROUP
    from .org_candidates import org_candidates
    from .pii_candidates import pii_candidates
    have = {(s, e, GROUP[k]) for s, e, k in candidates(text) + pii_candidates(text) + org_candidates(text)}
    return [x for x in spans if (x["start"], x["end"], x.get("group", "person")) not in have]
# 6. 法律文件裡的日期：案件事件日期（簽署、設定、匯款、起訴、登記、到職）＝個人行程日期（法律模式保留），出生日期＝要遮
DATE_TPL = ("系爭抵押權設定於{event}，而系爭承諾書簽立於{event2}，兩者時間顯有矛盾。", "被告{p}（{birth}生）於{event}簽立承諾書，承諾於{event2}前清償。",
            "承諾書簽署日期為{event}，而抵押權設定日期為{event2}。", "依土地登記謄本所示，{p}係於{event}以買賣為原因取得系爭土地，並於{event2}辦理抵押權設定登記。",
            "原告於{event}起訴，被告{p}於{event2}收受起訴狀繕本。", "兩造於{event}簽訂買賣契約，約定於{event2}交屋，惟被告{p}迄未給付尾款。",
            "被告{p}於{event}匯款新臺幣30萬元至原告帳戶，原告{q}於{event2}始發現。", "{p}，{birth}生，於{event}到職，{event2}離職。",
            "按{p}生於{birth}，於{event}行為時已滿十八歲。", "出生日期：{birth}\n到職日期：{event}\n離職日期：{event2}",
            "系爭借款係於{event}交付，借款人{p}之出生年月日為{birth}。", "查系爭承諾書簽署於{event}，距抵押權設定之{event2}已逾一年。",
            "{p}之出生日期為{birth}，與承諾書簽署日期{event}相距甚遠。", "本件車禍發生於{event}，原告{p}（{birth}生）因而受傷。")


def roc_date(rng, birth=False):
    y = rng.randint(40, 95) if birth else rng.randint(85, 114)
    m, d = rng.randint(1, 12), rng.randint(1, 28)
    return rng.choice((f"{y}年{m}月{d}日", f"民國{y}年{m}月{d}日", f"{y:03d}/{m:02d}/{d:02d}", f"{y}.{m}.{d}", f"{y + 1911}年{m}月{d}日"))


def render(tpl, fills, rng):
    """把 {p}/{q}（私人，要遮）、{k}（保留）換成假名，記錄位置；其他欄位照填。"""
    text, spans, i = "", [], 0
    while i < len(tpl):
        if tpl[i] == "{":
            j = tpl.index("}", i); key = tpl[i + 1:j]
            val = fills[key]
            if key in SPAN_KEYS:
                lab = SPAN_KEYS[key]
                sp = {"start": len(text), "end": len(text) + len(val)}
                spans.append(dict(sp, label=lab) if isinstance(lab, str) else dict(sp, label=lab[0], group=lab[1], tag=lab[2]))
            text += val; i = j + 1
        else:
            text += tpl[i]; i += 1
    return text, spans


def main():
    rng = random.Random(5)
    roads = []
    for f in glob.glob(os.path.join(os.path.dirname(__file__), "data", "roads_*.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            if r.get("road") and r.get("site_id"):
                roads.append((r["city"], r["site_id"][len(r["city"]):], r["road"]))
    from .candidates import surname_len
    personlike = [r for r in roads if surname_len(r[2])]  # 姓氏字開頭的路名（鄭成功路、林森北路）才是會混淆的
    docs = []
    for k in range(3000):
        city, dist, road = rng.choice(personlike if rng.random() < 0.6 else roads)
        _, _, road2 = rng.choice(roads)
        fills = {"p": sample_name(rng), "q": sample_name(rng), "road": road, "road2": road2, "city": city, "dist": dist, "n": str(rng.randint(1, 300))}
        t, s = render(rng.choice(ROAD_TPL), fills, rng)
        docs.append({"id": f"road#{k}", "text": t, "spans": s, "src": "aug"})
    for k in range(2500):
        fills = {"p": sample_name(rng), "k": sample_name(rng), "role": rng.choice(PARTY), "title": rng.choice(TITLES),
                 "title2": rng.choice(("法官", "審判長法官", "受命法官")), "tail": rng.choice(TAILS)}
        tpl = rng.choice(JI_TPL) if rng.random() < 0.7 else rng.choice(KEEP_TPL)
        t, s = render(tpl, fills, rng)
        docs.append({"id": f"ji#{k}", "text": t, "spans": s, "src": "aug"})
    # 3. 英文：品牌／App／英文地址／信尾敬語＝不是人名；英文人名＝要遮（同樣句型，讓模型看上下文分辨）
    for k in range(3000):
        first, last = rng.choice(EN_FIRST), rng.choice(EN_LAST)
        roman = rng.choice(ROMAN_NAMES)
        fills = {"p": rng.choice((f"{first} {last}", first, roman)), "q": rng.choice((first, roman)), "plat": rng.choice(BRANDS),
                 "plat2": rng.choice(BRANDS), "closing": rng.choice(CLOSINGS),
                 "addr": f"No. {rng.randint(1, 300)}, Sec. {rng.randint(1, 5)}, {rng.choice(EN_ROADS)} Rd., {rng.choice(EN_DISTS)} Dist., "
                         f"{rng.choice(EN_CITIES)} {rng.randint(100, 999)}, Taiwan (R.O.C.)"}
        t, sp = render(rng.choice(EN_TPL), fills, rng)
        docs.append({"id": f"en#{k}", "text": t, "spans": sp, "src": "aug"})
    # 4. 英文片語（病歷段落標題、職稱、信尾）與「人名＋店名」：都不是人；旁邊偶爾放一個真的私人當對照
    from .names import sample_surname
    for k in range(3000):
        nm = sample_name(rng)
        biz = rng.choice((nm + rng.choice(BIZ_SUFFIX), sample_surname(rng) + rng.choice("記家氏") + rng.choice(FOODS),
                          "阿" + rng.choice("宗明美珠成財發") + rng.choice(FOODS)))
        fills = {"biz": biz, "phrase": rng.choice(EN_PHRASES), "phrase2": rng.choice(EN_PHRASES), "p": sample_name(rng),
                 "q": rng.choice(EN_FIRST)}
        t, sp = render(rng.choice(NEG_TPL), fills, rng)
        docs.append({"id": f"neg#{k}", "text": t, "spans": sp, "src": "aug"})
    # 5. 公眾人物（保留）對照同姓一般人（要遮）；店名裡的「姓＋稱謂」（不是人）對照本人（要遮）；句首只寫名字；護照式英文姓名
    for k in range(4000):
        fig = rng.choice(PUBLIC)
        p = sample_name(rng)
        if rng.random() < 0.4:  # 同姓對照：模型不能看姓決定
            p = fig[0] + sample_name(rng, length=3)[1:]
        sur = sample_name(rng)[0]
        g3 = sample_name(rng, length=3)
        fills = {"fig": fig, "fig_shop": fig, "p": p, "q": g3[1:], "sur": sur, "sur_p": sur, "n": str(rng.randint(10, 999)),
                 "kin": rng.choice(KIN), "food": rng.choice(FOODS + BIZ_SUFFIX),
                 "shop": rng.choice(BIZ_SUFFIX), "pp": rng.choice(ROMAN_NAMES).upper().replace(" ", ", ", 1),
                 "event": rng.choice(EVENTS)}
        t, sp = render(rng.choice(PUB_TPL), fills, rng)
        docs.append({"id": f"pub#{k}", "text": t, "spans": sp, "src": "aug"})
    for k in range(3000):  # 6. 法律文件的日期：個人資料全標（人名＋個資），其他號碼候選＝不是
        fills = {"p": sample_name(rng), "q": sample_name(rng), "event": roc_date(rng), "event2": roc_date(rng), "birth": roc_date(rng, birth=True)}
        t, sp = render(rng.choice(DATE_TPL), fills, rng)
        docs.append({"id": f"date#{k}", "text": t, "spans": sp, "src": "aug", "annot": ["person", "pii"]})
    stats = collections.Counter()

    def put(kind, k, t, sp, annot):
        bad = _uncovered(t, sp)
        sp = [x for x in sp if x not in bad]  # 沒有候選的保留機構（7-ELEVEN、蝦皮）本來就不會被遮：拿掉標註就好
        ok = all(x.get("tag") == "ORGK" for x in bad)  # 其他標註沒有候選：整份丟掉
        stats[kind, ok] += 1
        if ok:
            docs.append({"id": f"{kind}#{k}", "text": t, "spans": sp, "src": "aug", "annot": annot})
    from .org_candidates import _listed_shorts
    from .surnames import JP_SURNAMES
    shorts = _listed_shorts()[0]
    cos = [(r["name"], r["short"]) for r in csv.DictReader(open(os.path.join(os.path.dirname(__file__), "data", "tw_listed_companies.csv"), encoding="utf-8"))
           if r["short"] in shorts and r["name"].endswith("有限公司")]
    amts = ("3萬", "12萬5,000", "50萬", "1,280,000", "8萬6,000", "200萬")
    for k in range(4000):  # 7. 上市櫃公司
        (full, short), (_, short_k) = rng.sample(cos, 2)
        fills = {"p": sample_name(rng), "full": full, "short": short, "short_k": short_k, "inc": rng.choice(INCIDENTAL),
                 "amt": rng.choice(amts), "n": str(rng.randint(2, 15))}
        r = rng.random()
        t, sp = render(rng.choice(CO_PARTY) if r < 0.5 else rng.choice(CO_INC) if r < 0.7 else rng.choice(CO_PARTY) + rng.choice(CO_INC), fills, rng)
        put("co", k, t, sp, ["person", "org"])
    for k in range(3000):  # 8. 英文暱稱（三成是 LINE 顯示名稱的「英文名＋中文姓」：CINDY林、林Cindy、Andy 鄧）
        n = rng.choice(NICKS)
        nick, sur = rng.choice((n.upper(), n.upper(), n)), sample_name(rng)[0]
        if rng.random() < 0.3:
            nick = rng.choice((f"{nick}{sur}", f"{sur}{n}", f"{n} {sur}", f"{nick} {sur}"))
        fills = {"nick": nick, "mobile": _mobile(rng), "p": sample_name(rng)}
        t, sp = render(rng.choice(NICK_TPL) + rng.choice(("", "\n" + rng.choice(NICK_TPL))), fills, rng)
        put("nick", k, t, sp, ["person", "pii"])
    for k in range(2000):  # 9. 日本人名
        sur = rng.choice(JP_SURNAMES)
        fills = {"jp": sur + rng.choice(("", "", " ", "　")) + rng.choice(JP_GIVEN), "jp2": rng.choice(JP_SURNAMES) + rng.choice(JP_GIVEN),
                 "jp_sur": sur, "p": sample_name(rng), "k": sample_name(rng)}
        t, sp = render(rng.choice(JP_TPL), fills, rng)
        put("jp", k, t, sp, ["person"])
    for k in range(2500):  # 10. 私人 vs 機構電話
        fills = {"land": _land(rng), "land_x": _land(rng), "land_x2": _land(rng), "mobile": _mobile(rng), "p": sample_name(rng), "k": sample_name(rng),
                 "d3": str(rng.randint(100, 999)), "d3b": str(rng.randint(100, 999)), "a": str(rng.randint(2, 8)),
                 "d8": f"{rng.randint(2000, 2999)}-{rng.randint(1000, 9999)}", "gu": rng.choice("智仁義禮信忠孝"), "dept": rng.choice(DEPTS)}
        t, sp = render(rng.choice(TEL_TPL) + rng.choice(("", "\n" + rng.choice(TEL_TPL))), fills, rng)
        put("tel", k, t, sp, ["person", "pii"])
    for k in range(2000):  # 11. 移工、外配的護照式姓名
        parts = PASS_NAMES[rng.choice(("vn", "vn", "id", "id", "th", "ph"))]
        name = " ".join(rng.choice(p) for p in parts) if rng.random() < 0.85 else rng.choice(parts[0])
        t, sp = render(rng.choice(PASS_TPL), {"pp2": name, "p": sample_name(rng), "n": str(rng.randint(2, 12))}, rng)
        put("pass", k, t, sp, ["person"])
    from .org_candidates import BRANDS as ORG_BRANDS
    for k in range(3000):  # 12. 連鎖、國營、大品牌：雇主／當事人 vs 順帶提到
        brand, brand_k = rng.sample(ORG_BRANDS, 2)
        fills = {"p": sample_name(rng), "brand": brand, "brand_b": brand + rng.choice(BRANCH_NAMES) + rng.choice(("門市", "分店", "營業處")),
                 "brand_k": brand_k, "n": str(rng.randint(2, 15)), "amt": rng.choice(amts)}
        r = rng.random()
        tpl = rng.choice(BRAND_PARTY) if r < 0.5 else rng.choice(BRAND_INC) if r < 0.75 else rng.choice(BRAND_PARTY) + rng.choice(BRAND_INC)
        t, sp = render(tpl, fills, rng)
        put("brand", k, t, sp, ["person", "org"])
    print("v11 擴增（留下／丟掉＝標註沒有候選）：", {k: f"{stats[k, True]}／{stats[k, False]}" for k in ("co", "nick", "jp", "tel", "pass", "brand")})
    os.makedirs(f"{D}/train", exist_ok=True)
    with open(f"{D}/train/aug_docs.jsonl", "w") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"擴增文件 {len(docs)} 份（路名 {len(roads)} 條）→ data/train/aug_docs.jsonl")


if __name__ == "__main__":
    t, s = render("{role}即{title}{p}{tail}", {"role": "被告", "title": "法官", "p": "林雅婷", "tail": "否認。"}, random.Random(0))
    assert t == "被告即法官林雅婷否認。" and t[s[0]["start"]:s[0]["end"]] == "林雅婷" and s[0]["label"] == "MASK"
    t2, s2 = render("{p}之出生日期為{birth}，與承諾書簽署日期{event}相距甚遠。", {"p": "林雅婷", "birth": "70年5月3日", "event": "93年6月25日"}, random.Random(0))
    assert [(t2[x["start"]:x["end"]], x["label"], x.get("group", "person")) for x in s2] == [
        ("林雅婷", "MASK", "person"), ("70年5月3日", "MASK", "pii"), ("93年6月25日", "KEEP", "pii")], s2
    main()
