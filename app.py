# app.py
from flask import Flask, render_template, request, jsonify, redirect, url_for
import pyodbc  # 使用pyodbc來連接MSSQL
import os
from datetime import datetime

app = Flask(__name__)

# 資料庫連接函數
def get_db_connection():
    try:
        conn = pyodbc.connect(
            'DRIVER={ODBC Driver 17 for SQL Server};'  # 或者使用其他可用的SQL Server驅動
            'SERVER=localhost;'                        # 資料庫伺服器地址
            'DATABASE=asset_management;'               # 資料庫名稱
            'UID=mis;'                          # 資料庫用戶名
            'PWD=7319;'                       # 資料庫密碼
        )
        return conn
    except pyodbc.Error as e:
        print(f"資料庫連接錯誤: {e}")
        return None

# 資料庫初始化函數 - 請在首次運行後註釋掉
def init_db():
    # 這裡您可以使用外部SQL腳本或在此處編寫初始化代碼
    # 請參考先前提供的SQL腳本來創建表格結構
    print("請使用SQL腳本初始化資料庫")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/asset_edit')
def asset_edit():
    return render_template('asset_edit.html')

@app.route('/asset_query')
def asset_query():
    return render_template('asset_query.html')

@app.route('/inventory_adjust_query')
def inventory_adjust_query():
    return render_template('inventory_adjust_query.html')

# API: 獲取所有資產類別
@app.route('/api/categories', methods=['GET'])
def get_categories():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '資料庫連接失敗'}), 500
    
    cursor = conn.cursor()
    cursor.execute('SELECT id, name FROM asset_categories ORDER BY name')
    
    # 將查詢結果轉換為字典列表
    categories = []
    for row in cursor.fetchall():
        categories.append({'id': row[0], 'name': row[1]})
    
    conn.close()
    
    return jsonify(categories)

# API: 新增資產類別
@app.route('/api/categories', methods=['POST'])
def add_category():
    category_name = request.json.get('name')
    if not category_name:
        return jsonify({'error': '類別名稱不能為空'}), 400
    
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '資料庫連接失敗'}), 500
    
    cursor = conn.cursor()
    try:
        # 新增類別
        cursor.execute('INSERT INTO asset_categories (name) VALUES (?)', (category_name,))
        conn.commit()
        
        # 獲取新增的ID
        cursor.execute('SELECT @@IDENTITY')
        new_id = int(cursor.fetchone()[0])
        
        # 記錄類別新增操作
        cursor.execute(
            'INSERT INTO category_transactions (category_id, category_name, action_type) VALUES (?, ?, ?)',
            (new_id, category_name, '新增類別')
        )
        
        conn.commit()
        conn.close()
        return jsonify({'id': str(new_id), 'name': category_name}), 201
    except pyodbc.IntegrityError:
        conn.close()
        return jsonify({'error': '類別名稱已存在'}), 400
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': f'新增失敗: {str(e)}'}), 500

# API: 刪除資產類別
@app.route('/api/categories/<int:category_id>', methods=['DELETE'])
def delete_category(category_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '資料庫連接失敗'}), 500
    
    cursor = conn.cursor()
    
    # 檢查類別是否存在
    cursor.execute('SELECT name FROM asset_categories WHERE id = ?', (category_id,))
    category_row = cursor.fetchone()
    if not category_row:
        conn.close()
        return jsonify({'error': '類別不存在'}), 404
    
    category_name = category_row[0]
    
    # 檢查該類別是否有資產
    cursor.execute('SELECT total_quantity FROM assets WHERE category_id = ?', (category_id,))
    asset_row = cursor.fetchone()
    if asset_row and asset_row[0] > 0:
        conn.close()
        return jsonify({'error': '該類別還有資產，無法刪除'}), 400
    
    try:
        # 記錄類別刪除操作
        cursor.execute(
            'INSERT INTO category_transactions (category_id, category_name, action_type) VALUES (?, ?, ?)',
            (category_id, category_name, '刪除類別')
        )
        
        # 刪除該類別的資產記錄（如果總數為0）
        cursor.execute('DELETE FROM assets WHERE category_id = ?', (category_id,))
        
        # 刪除類別
        cursor.execute('DELETE FROM asset_categories WHERE id = ?', (category_id,))
        
        conn.commit()
        conn.close()
        return jsonify({'success': True}), 200
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': f'刪除失敗: {str(e)}'}), 500

# API: 查詢庫存 (更新以顯示總數量、新舊資產數量)
# API: 根據日期查詢資產 (新增)
@app.route('/api/assets', methods=['GET'])
def get_assets():
    date_param = request.args.get('date')
    
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '資料庫連接失敗'}), 500
    
    cursor = conn.cursor()
    
    # 獲取所有資產類別
    cursor.execute('SELECT id, name FROM asset_categories ORDER BY name')
    categories = []
    for row in cursor.fetchall():
        categories.append({'id': row[0], 'name': row[1]})
    
    # 如果提供日期參數，查詢特定日期的資產狀態
    if date_param:
        # 轉換為結束時間 (當天 23:59:59)
        date_end = f"{date_param} 23:59:59"
        
        assets = []
        
        for category in categories:
            category_id = category['id']
            category_name = category['name']
            
            # 查詢當前資產情況
            cursor.execute('SELECT total_quantity, new_quantity, used_quantity FROM assets WHERE category_id = ?', (category_id,))
            current_asset_row = cursor.fetchone()
            current_total = current_asset_row[0] if current_asset_row else 0
            current_new = current_asset_row[1] if current_asset_row else 0
            current_used = current_asset_row[2] if current_asset_row else 0
            
            # 查詢給定日期後的所有交易
            cursor.execute('''
                SELECT transaction_type, operation_type, quantity 
                FROM transactions 
                WHERE category_id = ? AND timestamp > ?
                ORDER BY timestamp
            ''', (category_id, date_end))
            
            transactions_after_date = cursor.fetchall()
            
            # 從當前狀態反推指定日期的資產數量
            historical_total = current_total
            historical_new = current_new
            historical_used = current_used
            
            for tx in transactions_after_date:
                transaction_type = tx[0]
                operation_type = tx[1]
                quantity = tx[2]
                
                # 反向計算：對後來的進貨，需要減去；對後來的出貨，需要加回來
                if transaction_type == '入庫':
                    historical_total -= quantity
                    if operation_type == '購入':
                        historical_new -= quantity
                    elif operation_type == '收回':
                        historical_used -= quantity
                elif transaction_type == '出庫':
                    historical_total += quantity
                    # 如果交易記錄中有資產狀態，根據記錄反推
                    if operation_type == '發放':
                        if tx[2] == '新品':
                            historical_new += quantity
                        else:
                            historical_used += quantity
                    else:
                        # 對於送修和報廢，我們無法準確知道當時出庫的是哪種資產
                        # 這裡採用保守估計，盡量從舊品中扣
                        if historical_used >= quantity:
                            historical_used += quantity
                        else:
                            remaining = quantity - historical_used
                            historical_used += historical_used  # 先將舊品全部加回來
                            historical_new += remaining         # 剩餘的從新品加回來
                elif transaction_type == '銷存增加':
                    historical_total -= quantity
                    if tx[2] == '新品':
                        historical_new -= quantity
                    else:
                        historical_used -= quantity
                elif transaction_type == '銷存減少':
                    historical_total += quantity
                    if tx[2] == '新品':
                        historical_new += quantity
                    else:
                        historical_used += quantity
            
            # 確保數值不為負數
            historical_total = max(0, historical_total)
            historical_new = max(0, historical_new)
            historical_used = max(0, historical_used)
            
            assets.append({
                'id': str(category_id),
                'category_name': category_name,
                'total_quantity': historical_total,
                'new_quantity': historical_new,
                'used_quantity': historical_used
            })
        
        conn.close()
        return jsonify(assets)
    
    # 如果沒有日期參數，返回當前資產狀態
    # 獲取所有資產記錄
    cursor.execute('SELECT category_id, total_quantity, new_quantity, used_quantity FROM assets')
    assets_dict = {}
    for row in cursor.fetchall():
        assets_dict[row[0]] = {
            'total_quantity': row[1],
            'new_quantity': row[2],
            'used_quantity': row[3]
        }
    
    # 合併類別和資產數據，沒有記錄的類別顯示為0
    assets = []
    for category in categories:
        cat_id = category['id']
        if cat_id in assets_dict:
            assets.append({
                'id': str(cat_id),
                'category_name': category['name'],
                'total_quantity': assets_dict[cat_id]['total_quantity'],
                'new_quantity': assets_dict[cat_id]['new_quantity'],
                'used_quantity': assets_dict[cat_id]['used_quantity']
            })
        else:
            assets.append({
                'id': str(cat_id),
                'category_name': category['name'],
                'total_quantity': 0,
                'new_quantity': 0,
                'used_quantity': 0
            })
    
    conn.close()
    
    return jsonify(assets)

# API: 獲取特定類別的庫存數量 (更新以顯示總數量、新舊資產數量)
@app.route('/api/assets/category/<int:category_id>', methods=['GET'])
def get_category_asset(category_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '資料庫連接失敗'}), 500
    
    cursor = conn.cursor()
    
    # 檢查類別是否存在
    cursor.execute('SELECT name FROM asset_categories WHERE id = ?', (category_id,))
    category_row = cursor.fetchone()
    if not category_row:
        conn.close()
        return jsonify({'error': '類別不存在'}), 404
    
    category_name = category_row[0]
    
    # 獲取類別的庫存數量
    cursor.execute('SELECT total_quantity, new_quantity, used_quantity FROM assets WHERE category_id = ?', (category_id,))
    asset_row = cursor.fetchone()
    
    if asset_row:
        total_quantity = asset_row[0]
        new_quantity = asset_row[1]
        used_quantity = asset_row[2]
    else:
        total_quantity = new_quantity = used_quantity = 0
    
    conn.close()
    return jsonify({
        'category_id': str(category_id), 
        'category_name': category_name, 
        'total_quantity': total_quantity,
        'new_quantity': new_quantity,
        'used_quantity': used_quantity
    })

# API: 出庫資產 (更新以處理新舊資產)
@app.route('/api/assets/checkout', methods=['POST'])
def checkout_asset():
    data = request.json
    category_id = data.get('category_id')
    quantity = data.get('quantity', 0)
    operation_type = data.get('operation_type', '發放')  # 預設為發放
    asset_status = data.get('asset_status')  # 必須指定是新品或二手
    
    if not category_id or quantity <= 0:
        return jsonify({'error': '資產類別和數量不能為空，且數量必須大於0'}), 400
    
    if operation_type not in ['發放', '送修', '報廢']:
        return jsonify({'error': '無效的操作類型'}), 400
    
    # 所有出庫操作都必須指定資產狀態
    if asset_status not in ['新品', '二手']:
        return jsonify({'error': '必須指定資產狀態(新品或二手)'}), 400
    
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '資料庫連接失敗'}), 500
    
    cursor = conn.cursor()
    
    # 檢查類別是否存在
    cursor.execute('SELECT id FROM asset_categories WHERE id = ?', (category_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({'error': '資產類別不存在'}), 404
    
    # 檢查庫存是否足夠
    cursor.execute('SELECT id, total_quantity, new_quantity, used_quantity FROM assets WHERE category_id = ?', (category_id,))
    existing_asset_row = cursor.fetchone()
    
    if not existing_asset_row:
        conn.close()
        return jsonify({'error': '找不到該類別的庫存記錄'}), 404
    
    existing_id = existing_asset_row[0]
    total_quantity = existing_asset_row[1]
    new_quantity = existing_asset_row[2]
    used_quantity = existing_asset_row[3]
    
    # 檢查總庫存是否足夠
    if total_quantity < quantity:
        conn.close()
        return jsonify({'error': '總庫存不足'}), 400
    
    try:
        # 根據資產狀態更新相應的數量
        if asset_status == '新品':
            # 檢查新資產庫存是否足夠
            if new_quantity < quantity:
                conn.close()
                return jsonify({'error': '新資產庫存不足'}), 400
            
            # 更新新資產數量
            new_quantity -= quantity
        else:  # 二手
            # 檢查舊資產庫存是否足夠
            if used_quantity < quantity:
                conn.close()
                return jsonify({'error': '舊資產庫存不足'}), 400
            
            # 更新舊資產數量
            used_quantity -= quantity
        
        # 更新總數量
        total_quantity -= quantity
        
        # 更新資產數量
        cursor.execute(
            'UPDATE assets SET total_quantity = ?, new_quantity = ?, used_quantity = ? WHERE id = ?',
            (total_quantity, new_quantity, used_quantity, existing_id)
        )
        
        # 獲取客戶端IP地址
        ip_address = request.remote_addr
        
        # 記錄出庫交易
        cursor.execute(
            'INSERT INTO transactions (category_id, quantity, transaction_type, operation_type, asset_status, ip_address) VALUES (?, ?, ?, ?, ?, ?)',
            (category_id, quantity, '出庫', operation_type, asset_status, ip_address)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': f'出庫失敗: {str(e)}'}), 500

# API: 入庫資產 (更新以處理新舊資產)
@app.route('/api/assets/checkin', methods=['POST'])
def checkin_asset():
    data = request.json
    category_id = data.get('category_id')
    quantity = data.get('quantity', 0)
    operation_type = data.get('operation_type', '購入')  # 預設為購入
    
    if not category_id or quantity <= 0:
        return jsonify({'error': '資產類別和數量不能為空，且數量必須大於0'}), 400
    
    if operation_type not in ['購入', '收回']:
        return jsonify({'error': '無效的操作類型'}), 400
    
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '資料庫連接失敗'}), 500
    
    cursor = conn.cursor()
    
    # 檢查類別是否存在
    cursor.execute('SELECT id FROM asset_categories WHERE id = ?', (category_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({'error': '資產類別不存在'}), 404
    
    # 檢查該類別是否已有資產記錄
    cursor.execute('SELECT id, total_quantity, new_quantity, used_quantity FROM assets WHERE category_id = ?', (category_id,))
    existing_asset_row = cursor.fetchone()
    
    try:
        asset_status = None
        
        if existing_asset_row:
            existing_id = existing_asset_row[0]
            total_quantity = existing_asset_row[1]
            new_quantity = existing_asset_row[2]
            used_quantity = existing_asset_row[3]
            
            # 根據操作類型更新相應的數量
            if operation_type == '購入':
                # 購入的資產為新品
                new_quantity += quantity
                asset_status = '新品'
            else:  # 收回
                # 收回的資產為二手
                used_quantity += quantity
                asset_status = '二手'
            
            # 更新總數量
            total_quantity += quantity
            
            # 更新資產數量
            cursor.execute(
                'UPDATE assets SET total_quantity = ?, new_quantity = ?, used_quantity = ? WHERE id = ?',
                (total_quantity, new_quantity, used_quantity, existing_id)
            )
        else:
            # 新增資產記錄
            if operation_type == '購入':
                # 購入的資產為新品
                new_quantity = quantity
                used_quantity = 0
                asset_status = '新品'
            else:  # 收回
                # 收回的資產為二手
                new_quantity = 0
                used_quantity = quantity
                asset_status = '二手'
            
            total_quantity = quantity
            
            cursor.execute(
                'INSERT INTO assets (category_id, total_quantity, new_quantity, used_quantity) VALUES (?, ?, ?, ?)',
                (category_id, total_quantity, new_quantity, used_quantity)
            )
        
        # 獲取客戶端IP地址
        ip_address = request.remote_addr
        
        # 記錄入庫交易
        cursor.execute(
            'INSERT INTO transactions (category_id, quantity, transaction_type, operation_type, asset_status, ip_address) VALUES (?, ?, ?, ?, ?, ?)',
            (category_id, quantity, '入庫', operation_type, asset_status, ip_address)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': f'入庫失敗: {str(e)}'}), 500

# API: 銷存調整 (更新以處理新舊資產)

@app.route('/api/assets/adjust', methods=['POST'])
def adjust_asset():
    data = request.json
    category_id = data.get('category_id')
    quantity = data.get('quantity', 0)
    adjustment_type = data.get('adjustment_type', '增加')  # 增加 或 減少
    asset_status = data.get('asset_status')  # 'new'(新品), 'used'(二手)
    reason = data.get('reason', '')  # 新增的銷存原因欄位
    
    if not category_id or quantity <= 0:
        return jsonify({'error': '資產類別和數量不能為空，且數量必須大於0'}), 400
    
    if adjustment_type not in ['增加', '減少']:
        return jsonify({'error': '無效的調整類型'}), 400
    
    if asset_status not in ['新品', '二手']:
        return jsonify({'error': '必須指定資產狀態(新品或二手)'}), 400
        
    if not reason.strip():
        return jsonify({'error': '必須提供調整原因'}), 400
    
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '資料庫連接失敗'}), 500
    
    cursor = conn.cursor()
    
    # 檢查類別是否存在
    cursor.execute('SELECT id FROM asset_categories WHERE id = ?', (category_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({'error': '資產類別不存在'}), 404
    
    # 檢查該類別是否已有資產記錄
    cursor.execute('SELECT id, total_quantity, new_quantity, used_quantity FROM assets WHERE category_id = ?', (category_id,))
    existing_asset_row = cursor.fetchone()
    
    try:
        if existing_asset_row:
            existing_id = existing_asset_row[0]
            total_quantity = existing_asset_row[1]
            new_quantity = existing_asset_row[2]
            used_quantity = existing_asset_row[3]
            
            # 根據資產狀態和調整類型更新數量
            if adjustment_type == '增加':
                if asset_status == '新品':
                    new_quantity += quantity
                else:  # 二手
                    used_quantity += quantity
                
                total_quantity += quantity
            else:  # 減少
                if asset_status == '新品':
                    # 檢查新資產庫存是否足夠
                    if new_quantity < quantity:
                        conn.close()
                        return jsonify({'error': '新資產庫存不足，無法減少'}), 400
                    
                    new_quantity -= quantity
                else:  # 二手
                    # 檢查舊資產庫存是否足夠
                    if used_quantity < quantity:
                        conn.close()
                        return jsonify({'error': '舊資產庫存不足，無法減少'}), 400
                    
                    used_quantity -= quantity
                
                total_quantity -= quantity
            
            # 更新資產數量
            cursor.execute(
                'UPDATE assets SET total_quantity = ?, new_quantity = ?, used_quantity = ? WHERE id = ?',
                (total_quantity, new_quantity, used_quantity, existing_id)
            )
        else:
            # 如果是減少操作但沒有現有記錄
            if adjustment_type == '減少':
                conn.close()
                return jsonify({'error': '沒有庫存記錄，無法減少'}), 400
            
            # 新增資產記錄（只有增加操作）
            if asset_status == '新品':
                new_quantity = quantity
                used_quantity = 0
            else:  # 二手
                new_quantity = 0
                used_quantity = quantity
            
            total_quantity = quantity
            
            cursor.execute(
                'INSERT INTO assets (category_id, total_quantity, new_quantity, used_quantity) VALUES (?, ?, ?, ?)',
                (category_id, total_quantity, new_quantity, used_quantity)
            )
        
        # 獲取客戶端IP地址
        ip_address = request.remote_addr
        
        # 記錄銷存交易，包含原因
        transaction_type = '銷存增加' if adjustment_type == '增加' else '銷存減少'
        cursor.execute(
            'INSERT INTO transactions (category_id, quantity, transaction_type, operation_type, asset_status, reason, ip_address) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (category_id, quantity, transaction_type, adjustment_type, asset_status, reason, ip_address)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': f'調整失敗: {str(e)}'}), 500

# API: 查詢交易記錄 (更新以包含資產狀態)
@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '資料庫連接失敗'}), 500
    
    cursor = conn.cursor()
    
    # 查詢資產交易
    query_assets = '''
    SELECT t.id, c.name as category_name, t.quantity, t.transaction_type, t.operation_type, 
           t.asset_status, t.ip_address, t.timestamp, 'asset' as record_type
    FROM transactions t
    JOIN asset_categories c ON t.category_id = c.id
    '''
    
    # 查詢類別交易
    query_categories = '''
    SELECT ct.id, ct.category_name, 0 as quantity, ct.action_type as transaction_type, 
           '' as operation_type, NULL as asset_status, '' as ip_address, ct.timestamp, 'category' as record_type
    FROM category_transactions ct
    '''
    
    params = []
    if start_date and end_date:
        # MSSQL的日期格式可能需要調整
        query_assets += ' WHERE t.timestamp BETWEEN ? AND ?'
        query_categories += ' WHERE ct.timestamp BETWEEN ? AND ?'
        params = [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]
    
    # 合併兩個查詢 (MSSQL的UNION語法)
    query = query_assets
    if params:
        query += " UNION ALL " + query_categories + " ORDER BY timestamp DESC"
        cursor.execute(query, params + params)  # 需要重複參數
    else:
        query += " UNION ALL " + query_categories + " ORDER BY timestamp DESC"
        cursor.execute(query)
    
    # 轉換查詢結果為字典列表
    transactions = []
    columns = [column[0] for column in cursor.description]
    for row in cursor.fetchall():
        transaction = dict(zip(columns, row))
        
        # 將datetime轉換為字符串格式
        if 'timestamp' in transaction and transaction['timestamp']:
            transaction['timestamp'] = transaction['timestamp'].isoformat()
        
        # 將ID轉換為字符串
        if 'id' in transaction:
            transaction['id'] = str(transaction['id'])
            
        transactions.append(transaction)
    
    conn.close()
    
    return jsonify(transactions)

@app.route('/api/inventory-adjust-records', methods=['GET'])
def get_inventory_adjust_records():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    keyword = request.args.get('keyword', '').lower()
    
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '資料庫連接失敗'}), 500
    
    cursor = conn.cursor()
    
    # 構建查詢銷存記錄的SQL
    query = '''
    SELECT t.id, c.name as category_name, t.quantity, t.transaction_type, t.operation_type, 
           t.asset_status, t.ip_address, t.reason, t.timestamp
    FROM transactions t
    JOIN asset_categories c ON t.category_id = c.id
    WHERE t.transaction_type IN ('銷存增加', '銷存減少')
    '''
    
    params = []
    if start_date and end_date:
        query += ' AND t.timestamp BETWEEN ? AND ?'
        params = [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]
    
    query += ' ORDER BY t.timestamp DESC'
    
    cursor.execute(query, params)
    
    # 轉換查詢結果為字典列表
    records = []
    columns = [column[0] for column in cursor.description]
    for row in cursor.fetchall():
        record = dict(zip(columns, row))
        
        # 如果有關鍵字搜尋，過濾結果
        if keyword:
            category_name = record['category_name'].lower() if record['category_name'] else ''
            reason = record['reason'].lower() if record['reason'] else ''
            
            if keyword not in category_name and keyword not in reason:
                continue
        
        # 將datetime轉換為字符串格式
        if 'timestamp' in record and record['timestamp']:
            record['timestamp'] = record['timestamp'].isoformat()
        
        # 將ID轉換為字符串
        if 'id' in record:
            record['id'] = str(record['id'])
            
        records.append(record)
    
    conn.close()
    
    return jsonify(records)

if __name__ == '__main__':
    # 監聽所有網路介面，便於內網訪問
    app.run(host='192.168.110.103', port=5000, debug=False)