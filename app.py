import os
import json
import math
from dotenv import load_dotenv
from pathlib import Path

dotenv_path = Path('.env')
load_dotenv(dotenv_path=dotenv_path)
from flask import Flask, request, abort, render_template
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, PostbackEvent,
    QuickReply, QuickReplyButton, MessageAction, PostbackAction,
    FlexSendMessage, BubbleContainer, BoxComponent, TextComponent,
    ButtonComponent, SeparatorComponent, ImageComponent
)
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///linebot_estimate.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# LINE Bot API設定
print("🔍 讀到的 TOKEN 是：", os.getenv("CHANNEL_ACCESS_TOKEN"))
line_bot_api = LineBotApi(os.getenv("CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("CHANNEL_SECRET"))



# 店家LINE User ID
STORE_OWNER_LINE_USER_ID = "U20b92eb75ce168c461eebfac446a8769"

# 載入服務項目
with open('services.json', 'r', encoding='utf-8') as f:
    SERVICES = json.load(f)

ITEMS_PER_PAGE = 10

# 資料庫模型
class UserSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    line_user_id = db.Column(db.String(100), nullable=False, unique=True)
    current_step = db.Column(db.String(50), default='start')
    selected_items = db.Column(db.Text, default='[]')
    current_page = db.Column(db.Integer, default=1)
    pending_item = db.Column(db.String(200), nullable=True)
    contact_step = db.Column(db.Integer, default=0)
    name = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    visit_time = db.Column(db.String(100), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Estimate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    line_user_id = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.Text, nullable=True)
    visit_time = db.Column(db.String(100), nullable=True)
    items = db.Column(db.Text, nullable=False)
    total_low = db.Column(db.Integer, nullable=False)
    total_high = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# 建立資料庫表格
with app.app_context():
    db.create_all()

def get_or_create_session(user_id):
    session = UserSession.query.filter_by(line_user_id=user_id).first()
    if not session:
        session = UserSession(line_user_id=user_id)
        db.session.add(session)
        db.session.commit()
    return session

def create_service_selection_message(page=1):
    """建立服務選擇的Quick Reply訊息"""
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_services = SERVICES[start_idx:end_idx]
    
    quick_reply_buttons = []
    
    # 添加服務項目按鈕
    for service in page_services:
        quick_reply_buttons.append(
            QuickReplyButton(
                action=PostbackAction(
                    label=service['name'][:20],  # LINE限制20字元
                    data=f"select_service:{service['name']}"
                )
            )
        )
    
    # 添加分頁按鈕
    total_pages = math.ceil(len(SERVICES) / ITEMS_PER_PAGE)
    if page < total_pages:
        quick_reply_buttons.append(
            QuickReplyButton(
                action=PostbackAction(
                    label="➕ 下一頁",
                    data=f"next_page:{page + 1}"
                )
            )
        )
    
    if page > 1:
        quick_reply_buttons.append(
            QuickReplyButton(
                action=PostbackAction(
                    label="⬅️ 上一頁",
                    data=f"prev_page:{page - 1}"
                )
            )
        )
    
    # 添加完成選擇按鈕
    quick_reply_buttons.append(
        QuickReplyButton(
            action=PostbackAction(
                label="✅ 完成選擇",
                data="finish_selection"
            )
        )
    )
    
    quick_reply = QuickReply(items=quick_reply_buttons)
    
    return TextSendMessage(
        text=f"請問您需要哪些服務？（第 {page} 頁）",
        quick_reply=quick_reply
    )

def create_estimate_flex_message(session, selected_items):
    """建立估價單Flex Message"""
    # 計算總金額
    total_low = sum(item['total_low'] for item in selected_items)
    total_high = sum(item['total_high'] for item in selected_items)
    
    # 建立項目明細
    items_components = []
    for item in selected_items:
        print(item)
        remark = item.get('remark', '')

    # 🔧 專人估價的處理
        if item['total_low'] == 0 and item['total_high'] == 0:
            item_text = f"▫️ {item['name']} ×{item['quantity']}{item['unit']} ➜ 💬 將由專人聯繫報價"
        else:
            item_text = f"▫️ {item['name']} ×{item['quantity']}{item['unit']} ➜ NT${item['total_low']:,} ~ NT${item['total_high']:,}"

        if remark:
            item_text += f"\n  📌 {remark}"

        items_components.append(
            TextComponent(
                text=item_text,
                size="sm",
                wrap=True
            )
        )

    
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                ImageComponent(
                    url="https://i.postimg.cc/BnPL07jc/line-oa-chat-250628-214335.jpg",
                    size="md",
                    aspect_mode="fit",
                    aspect_ratio="1:1",
                    align="center",
                    gravity="center",
                    margin="none"
                ),
                TextComponent(
                    text="心感覺企業",
                    size="sm",
                    align="center",
                    gravity="center",
                    color="#888888",
                    margin="xs"
                ),
                TextComponent(text="📥 心感覺估價單", weight="bold", size="xl", margin="md"),
                SeparatorComponent(margin="md"),
                TextComponent(text=f"👤 {session.name}", margin="md"),
                TextComponent(text=f"📞 {session.phone}"),
                TextComponent(text=f"📍 {session.address}", wrap=True),
                TextComponent(text=f"📅 {session.visit_time}"),
                SeparatorComponent(margin="md"),
                TextComponent(text="🔧 項目明細：", weight="bold", margin="md"),
                *items_components,
                SeparatorComponent(margin="md"),
                TextComponent(
                    text=f"💰 總金額：NT${total_low:,} ~ NT${total_high:,}",
                    weight="bold",
                    size="lg",
                    margin="md",
                    wrap=True
                )
            ]
        ),
        footer=BoxComponent(
            layout="vertical",
            contents=[
                ButtonComponent(
                    action=PostbackAction(
                        label="✅ 我要預約",
                        data="confirm_booking"
                    ),
                    style="primary"
                )   
            ]
        )
    )
    
    return FlexSendMessage(alt_text="估價單", contents=bubble)

@app.route("/form", methods=["GET"])
def show_form():
    return render_template("form.html")

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    print(f"🆔 使用者 ID: {user_id}")
    text = event.message.text
    session = get_or_create_session(user_id)
    
    if text == "我要估價":
        # 重置會話狀態
        session.current_step = "selecting"
        session.current_page = 1
        session.selected_items = "[]"
        session.contact_step = 0
        session.name = None
        session.phone = None
        session.address = None
        session.visit_time = None
        db.session.commit()
        
        reply_message = create_service_selection_message(1)
        line_bot_api.reply_message(event.reply_token, reply_message)

    elif text == "查看已選項目":
        selected_items = json.loads(session.selected_items)
        if not selected_items:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="您尚未選擇任何服務項目。")
            )
        else:
            details = "\n".join([
                f"{idx+1}. {item['name']} ×{item['quantity']}{item['unit']} ➜ NT${item['total_low']} ~ NT${item['total_high']}"
                for idx, item in enumerate(selected_items)
            ])
            total_low = sum(i["total_low"] for i in selected_items)
            total_high = sum(i["total_high"] for i in selected_items)

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"🧾 已選項目：\n{details}\n\n💰 總金額：NT${total_low} ~ NT${total_high}")
            )    
    elif text.startswith("✂️ 刪除第") or text.startswith("刪除第"):
        try:
            messages = []  # ✅ 先定義 messages
            # 取得要刪除的項目編號
            index_str = text.replace("✂️ 刪除第", "").replace("刪除第", "").replace("項", "").strip()
            index = int(index_str) - 1  # 使用者輸入是第1項，但list是從0開始

            selected_items = json.loads(session.selected_items)
            if index < 0 or index >= len(selected_items):
                raise IndexError

            removed_item = selected_items.pop(index)  # 刪除指定項目
            session.selected_items = json.dumps(selected_items)
            db.session.commit()

            # 回覆刪除成功訊息
            reply = f"✅ 已成功刪除第{index+1}項：{removed_item['name']}"
            if not selected_items:
                reply += "\n（目前已無任何服務項目）"
            else:
                reply += "\n\n" + generate_selected_items_summary(selected_items)
                reply += "\n✏️ 如需繼續刪除，請再輸入：✂️ 刪除第N項"

            messages.append(TextSendMessage(text=reply))

            if selected_items:
                  messages.append(FlexSendMessage(
                      alt_text="請確認估價",
                      contents={
                          "type": "bubble",
                          "body": {
                              "type": "box",
                              "layout": "vertical",
                              "spacing": "md",
                              "contents": [
                                  {
                                      "type": "text",
                                      "text": "✅ 若無需修改，請點下方按鈕確認估價",
                                      "wrap": True
                                  }
                                ]
                            },
                            "footer": {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {
                                        "type": "button",
                                        "action": {
                                            "type": "postback",
                                            "label": "✅ 確認估價",
                                            "data": "confirm_estimate"
                                        },
                                        "style": "primary"
                                    }
                                ]
                            }
                        }
                    ))                                    
        
            line_bot_api.reply_message(event.reply_token, messages)
                
        except (ValueError, IndexError):
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❗請輸入正確的格式，例如：✂️ 刪除第2項")
            )
    elif (text.startswith("📝 修改第") or text.startswith("修改第")) and "為" in text:
        try:
            # 取得要修改的項目編號與新的數量
            index_str = text.replace("📝 修改第", "").replace("修改第", "").split("項為")[0].strip()
            new_qty_str = text.split("項為")[1].replace("個", "").strip()
            index = int(index_str) - 1  # 使用者輸入從1開始
            new_quantity = int(new_qty_str)

            selected_items = json.loads(session.selected_items)
            if index < 0 or index >= len(selected_items) or new_quantity <= 0:
                raise IndexError

            item = selected_items[index]

            if item["price_low"] is None:
                reply = f"❗ 此項目為專人報價，無法修改數量。"
            else:
                item["quantity"] = new_quantity
                item["total_low"] = item["price_low"] * new_quantity
                item["total_high"] = item["price_high"] * new_quantity
                selected_items[index] = item
                session.selected_items = json.dumps(selected_items)
                db.session.commit()

                reply = f"✅ 已成功將第{index+1}項《{item['name']}》修改為 {new_quantity}{item['unit']}\n"
                reply += f"新估價 ➜ NT${item['total_low']:,} ~ NT${item['total_high']:,}"

                reply += "\n\n" + generate_selected_items_summary(selected_items)


            messages = [TextSendMessage(text=reply)]

            if selected_items:
                messages.append(FlexSendMessage(
                    alt_text="請確認估價",
                    contents={
                        "type": "bubble",
                        "body": {
                            "type": "box",
                            "layout": "vertical",
                            "spacing": "md",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "✅ 若無需修改，請點下方按鈕確認估價",
                                    "wrap": True
                                }
                            ]
                        },
                        "footer": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "button",
                                    "action": {
                                        "type": "postback",
                                        "label": "✅ 確認估價",
                                        "data": "confirm_estimate"
                                    },
                                    "style": "primary"
                                }
                            ]
                        }
                    }
                ))

                line_bot_api.reply_message(event.reply_token, messages)

        except (ValueError, IndexError):
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❗ 請輸入正確的格式，例如：📝 修改第2項為5個")
            )

    elif session.current_step == "quantity_input":
        # 處理數量輸入
        try:
            quantity = int(text)
            if quantity <= 0:
                raise ValueError
                
            # 找到對應的服務項目
            service = next(s for s in SERVICES if s['name'] == session.pending_item)
            
            # 計算價格
            if service.get('price_low') is None:  # 專人報價項目
                total_low = 0
                total_high = 0
                price_text = "請專人報價"
            else:
                total_low = service['price_low'] * quantity
                total_high = service['price_high'] * quantity
                price_text = f"NT${total_low:,} ~ NT${total_high:,}"
            
            # 添加到已選項目
            selected_items = json.loads(session.selected_items)
            selected_items.append({
                'name': service['name'],
                'unit': service['unit'],
                'quantity': quantity,
                'price_low': service['price_low'],
                'price_high': service['price_high'],
                'total_low': total_low,
                'total_high': total_high,
                'remark': service.get('remark', '')
            })
            session.selected_items = json.dumps(selected_items)
            session.current_step = "selecting"
            session.pending_item = None
            db.session.commit()
            
            reply_text = f"{service['name']} 共 {quantity}{service['unit']}\n估價金額約 {price_text}\n✅ 已加入估價紀錄"
            reply_message = [
                TextSendMessage(text=reply_text),
                create_service_selection_message(session.current_page)
            ]
            line_bot_api.reply_message(event.reply_token, reply_message)
            
        except ValueError:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請輸入有效的數量（正整數）")
            )
            
    elif session.current_step == "contact_info":
        # 處理聯絡資訊輸入
        if session.contact_step == 0:  # 姓名
            session.name = text
            session.contact_step = 1
            db.session.commit()
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="2️⃣ 請輸入您的電話號碼：")
            )
        elif session.contact_step == 1:  # 電話
            session.phone = text
            session.contact_step = 2
            db.session.commit()
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="3️⃣ 請輸入施工地址：")
            )
        elif session.contact_step == 2:  # 地址
            session.address = text
            session.contact_step = 3
            db.session.commit()
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="4️⃣ 請輸入勘場時間：")
            )
        elif session.contact_step == 3:  # 勘場時間
            session.visit_time = text
            session.current_step = "completed"
            db.session.commit()
            
            # 生成估價單
            selected_items = json.loads(session.selected_items)
            flex_message = create_estimate_flex_message(session, selected_items)
            line_bot_api.reply_message(event.reply_token, flex_message)

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data
    session = get_or_create_session(user_id)
    
    if data.startswith("select_service:"):
        service_name = data.replace("select_service:", "")
        service = next(s for s in SERVICES if s['name'] == service_name)
        
        if service.get('price_low') is None:  # 專人報價項目
            # 直接添加到已選項目
            selected_items = json.loads(session.selected_items)
            selected_items.append({
                'name': service['name'],
                'unit': service['unit'],
                'quantity': 1,
                'price_low': None,
                'price_high': None,
                'total_low': 0,
                'total_high': 0
            })
            session.selected_items = json.dumps(selected_items)
            db.session.commit()
            
            reply_message = [
                TextSendMessage(text=f"{service['name']}\n✅ 已加入估價紀錄（請專人報價）"),
                create_service_selection_message(session.current_page)
            ]
        else:
            # 需要輸入數量
            session.current_step = "quantity_input"
            session.pending_item = service_name
            db.session.commit()
            
            reply_message = [
                TextSendMessage(text=f"請問 {service_name} 需要幾{service['unit']}？")
            ]
        
        line_bot_api.reply_message(event.reply_token, reply_message)
        
    elif data.startswith("next_page:"):
        page = int(data.replace("next_page:", ""))
        session.current_page = page
        db.session.commit()
        
        reply_message = create_service_selection_message(page)
        line_bot_api.reply_message(event.reply_token, reply_message)
        
    elif data.startswith("prev_page:"):
        page = int(data.replace("prev_page:", ""))
        session.current_page = page
        db.session.commit()
        
        reply_message = create_service_selection_message(page)
        line_bot_api.reply_message(event.reply_token, reply_message)
        
    elif data == "finish_selection":
        selected_items = json.loads(session.selected_items)
        if not selected_items:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="您尚未選擇任何服務項目，請先選擇服務項目。")
            )
        else:
            # 顯示已選項目 + 提示可修改
            details = "\n".join([
                f"{idx+1}. {item['name']} ×{item['quantity']}{item['unit']} ➜ NT${item['total_low']} ~ NT${item['total_high']}"
                for idx, item in enumerate(selected_items)
            ])
            total_low = sum(i["total_low"] for i in selected_items)
            total_high = sum(i["total_high"] for i in selected_items)

            reply = TextSendMessage(
                text=(
                    f"🧾 您已選擇以下項目：\n{details}\n\n"
                    f"💰 預估總金額：NT${total_low} ~ NT${total_high}\n\n"
                    "🔧 如需修改，請輸入：📝 修改第N項為X個\n"
                    "✂️ 如需刪除，請輸入：✂️ 刪除第N項\n\n"
                    "✅ 若無需修改，請點選下方【確認估價】開始填寫聯絡資料"
                )
            )

            confirm_button = FlexSendMessage(
                alt_text="請確認估價",
                contents={
                    "type": "bubble",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "md",
                        "contents": [
                            {
                                "type": "text",
                                "text": "✅ 若無需修改，請點下方按鈕確認估價",
                                "wrap": True
                            }
                        ]
                    },
                    "footer": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {
                                "type": "button",
                                "action": {
                                    "type": "postback",
                                    "label": "✅ 確認估價",
                                    "data": "confirm_estimate"
                                },
                                "style": "primary"
                            }
                        ]
                    }
                }
            )

            line_bot_api.reply_message(
                event.reply_token,
                [reply, confirm_button]
            )
            return
        
    elif data == "confirm_estimate":
        # 使用者點下「✅ 確認估價」後，開始進入聯絡資料填寫流程
        session.current_step = "contact_info"
        session.contact_step = 0
        db.session.commit()
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="1️⃣ 請輸入您的姓名：")
        )
  

    elif data == "confirm_booking":
        # 確認預約
        selected_items = json.loads(session.selected_items)
        total_low = sum(item['total_low'] for item in selected_items)
        total_high = sum(item['total_high'] for item in selected_items)
        
        # 儲存估價單到資料庫
        estimate = Estimate(
            line_user_id=user_id,
            name=session.name,
            phone=session.phone,
            address=session.address,
            visit_time=session.visit_time,
            items=session.selected_items,
            total_low=total_low,
            total_high=total_high,
            status='confirmed'
        )
        db.session.add(estimate)
        db.session.commit()
        
        # 發送確認訊息給客戶
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ 已收到您的預約申請，此估價為初估，還是依實際現場報價為主，我們將盡快與您聯繫！")
        )
        
        details = "\n".join([
            f"▫️ {item['name']} ×{item['quantity']}{item['unit']} ➜ NT${item['total_low']:,} ~ NT${item['total_high']:,}"
            for item in selected_items
        ])    

        # 發送通知給店家
        notification_text = f"""💬 有一筆新的估價申請
        👤 {session.name}｜📞 {session.phone}
        📍 {session.address}
        ⏰ {session.visit_time}
        🧾 明細：
        {details}

        💰 總金額：NT${total_low:,} ~ NT${total_high:,}"""
        
        try:
            line_bot_api.push_message(
                STORE_OWNER_LINE_USER_ID,
                TextSendMessage(text=notification_text)
            )
            print("✅ 推播成功")  # 這行幫你看有沒有送出
        except Exception as e:
            print(f"❌ 推播失敗: {e}")  # 這行幫你看到錯誤原因
            
    elif data == "modify_estimate":
        # 修改估價（重新開始流程）
        session.current_step = "selecting"
        session.current_page = 1
        db.session.commit()
        
        reply_message = create_service_selection_message(1)
        line_bot_api.reply_message(event.reply_token, reply_message)

@app.route('/submit-form', methods=['POST'])
def submit_form():
    try:
        data = request.form.to_dict()
        print("📥 收到表單資料：", data)

        user_id = data.get("user_id")
        name = data.get("name")
        phone = data.get("phone")
        address = data.get("address")
        visit_time = data.get("visit_time")

        # 處理選項
        selected_items = []
        total_low = 0
        total_high = 0

        for key, value in data.items():
            if key.startswith("service_") and value.isdigit():
                service_name = key.replace("service_", "")
                quantity = int(value)
                service = next((s for s in SERVICES if s['name'] == service_name), None)
                if service:
                    price_low = service['price_low'] or 0
                    price_high = service['price_high'] or 0
                    item = {
                        "name": service_name,
                        "unit": service["unit"],
                        "quantity": quantity,
                        "price_low": price_low,
                        "price_high": price_high,
                        "total_low": price_low * quantity,
                        "total_high": price_high * quantity
                    }
                    total_low += item["total_low"]
                    total_high += item["total_high"]
                    selected_items.append(item)

        # 存入資料庫
        estimate = Estimate(
            line_user_id=user_id,
            name=name,
            phone=phone,
            address=address,
            visit_time=visit_time,
            items=json.dumps(selected_items, ensure_ascii=False),
            total_low=total_low,
            total_high=total_high,
            status="confirmed"
        )
        db.session.add(estimate)
        db.session.commit()

        # 通知店家
        detail_lines = [
            f"▫️ {item['name']} ×{item['quantity']}{item['unit']} ➜ NT${item['total_low']} ~ NT${item['total_high']}"
            for item in selected_items
        ]
        detail_text = "\n".join(detail_lines)
        notification = f"""💬 有一筆新的 LIFF 表單估價單：
👤 {name}｜📞 {phone}
📍 {address}
⏰ {visit_time}
🧾 項目明細：
{detail_text}

💰 總金額：NT${total_low:,} ~ NT${total_high:,}
"""

        line_bot_api.push_message(STORE_OWNER_LINE_USER_ID, TextSendMessage(text=notification))

        return "OK"

    except Exception as e:
        print("❌ 表單提交處理失敗：", e)
        return "錯誤：" + str(e), 500


@app.route('/')
def index():
    return app.send_static_file('index.html')

# 🔧 補上顯示已選項目與總金額的函式
def generate_selected_items_summary(selected_items):
    summary = "📋 已選項目：\n"
    total_low = 0
    total_high = 0
    for idx, item in enumerate(selected_items):
        summary += f"{idx+1}. {item['name']} ×{item['quantity']}{item['unit']} ➜ NT${item['total_low']} ~ NT${item['total_high']}\n"
        total_low += item['total_low']
        total_high += item['total_high']
    summary += f"\n💰 預估總金額：NT${total_low} ~ NT${total_high}"
    return summary


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

