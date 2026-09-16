from datetime import datetime, timezone, timedelta
from copy import deepcopy


def default_settings():
    return {
        'revision': 1, 'dailyTarget': 15, 'monthlyTarget': '5000',
        'dailyOrders': 15, 'advancePerOrder': '25', 'cashCycle': 21,
        'bankBalance': '20000', 'committed': '0', 'reserve': '5000',
        'domesticDays': 2, 'warehouseDays': 1, 'shipDeadlineDays': 7,
        'rules': {'fx': '0.125', 'commission': '12', 'platformShipping': '5.6',
                  'shippingCap': '100', 'transaction': '2.24', 'installment': '8.24',
                  'growth': '1.5', 'marketing': '0', 'receiving': '0.7',
                  'orderFee': '5', 'targetMargin': '20', 'targetProfit': '10',
                  'verified': False, 'source': 'Linear v0.2 历史截图摘录 · 仅为演示种子，未对账',
                  'version': 'DEMO-1'},
        'pools': [{'name': '样品与验证', 'amount': 1500, 'color': '#a4bcce'},
                  {'name': '首轮出单采购', 'amount': 5000, 'color': '#eb633d'},
                  {'name': '物流与云仓', 'amount': 3000, 'color': '#f39f65'},
                  {'name': '测试推广', 'amount': 2000, 'color': '#dfba79'},
                  {'name': '工具与运营', 'amount': 1000, 'color': '#b7bdc5'},
                  {'name': '滚动采购缓冲', 'amount': 2500, 'color': '#577c85'},
                  {'name': '应急保留', 'amount': 5000, 'color': '#243d4b'}],
    }


def seed_suppliers():
    return [
        {'id': 'supplier-1', 'name': '宁波家居供应商 A', 'category': '家居收纳', 'leadDays': 1, 'stock': 320, 'verified': True, 'dropship': True, 'note': '示例供应商 · 需补充正式报价和凭证', 'revision': 1, 'demo': True},
        {'id': 'supplier-2', 'name': '义乌日用供应商 B', 'category': '日用百货', 'leadDays': 2, 'stock': 180, 'verified': True, 'dropship': True, 'note': '示例供应商 · 可作为候选备用货源', 'revision': 1, 'demo': True},
        {'id': 'supplier-3', 'name': '深圳配件供应商 C', 'category': '数码配件', 'leadDays': 4, 'stock': 0, 'verified': False, 'dropship': True, 'note': '示例异常 · 库存和发货时效待确认', 'revision': 1, 'demo': True},
    ]


def seed_products():
    expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    specs = [
        ('抽屉分隔收纳盒', 'Drawer Organizer Set · 6 Pieces', '家居收纳', '549', '12.5', '11.5', 280, 'supplier-1', [18, 12, 22, 18, 9, 8], 'PP plastic', 'Assorted sizes', '6 organizer boxes'),
        ('硅胶水槽沥水垫', 'Silicone Sink Splash Guard', '厨房用品', '399', '8.6', '8', 160, 'supplier-2', [16, 12, 22, 17, 8, 8], 'Silicone', '37 × 14 cm', '1 splash guard'),
        ('旅行压缩收纳袋', 'Travel Packing Bags · 4 Pieces', '旅行用品', '499', '13', '9.5', 210, 'supplier-1', [17, 11, 22, 18, 8, 8], 'Polyester', 'Mixed sizes', '4 packing bags'),
        ('可折叠桌面手机支架', 'Foldable Phone Stand', '数码配件', '199', '9.8', '9', 190, 'supplier-3', [15, 8, 10, 8, 7, 7], 'ABS plastic', '10 × 7 cm', '1 phone stand'),
        ('宠物外出拾便袋套装', 'Pet Waste Bags with Dispenser', '宠物日用', '299', '5.5', '7', 130, 'supplier-2', [15, 12, 19, 17, 9, 7], 'PE bags', '22 × 30 cm per bag', '6 rolls and 1 dispenser'),
        ('免打孔墙面收纳架', 'Wall Mounted Storage Shelf', '家居收纳', '599', '16', None, None, 'supplier-1', [16, 11, 18, 15, 6, 8], 'ABS plastic', '30 × 12 cm', '1 shelf'),
        ('桌面理线夹组合', 'Desk Cable Clips · 8 Pieces', '数码配件', '329', '5.8', '6.5', 80, 'supplier-2', [15, 11, 23, 18, 9, 8], 'Silicone', '2 × 2 cm each', '8 clips'),
        ('运动速干毛巾', 'Sports Towel', '运动用品', '349', '7.2', '7.5', 100, 'supplier-2', [16, 10, 20, 17, 9, 7], 'Microfiber', '30 × 100 cm', '1 towel'),
    ]
    products = []
    for i, (name, en, category, price, purchase, sls, weight, supplier, scores, material, size, pack) in enumerate(specs):
        p = {'id': f'product-{i+1}', 'name': name, 'englishName': en, 'category': category,
             'price': price, 'marketMax': str(int(price) + 100), 'buyerShipping': '0',
             'supplierId': supplier, 'supplierSku': f'DEMO-{i+1:03}', 'weight': weight,
             'payment': 'normal', 'orderFeeExempt': False, 'scores': scores,
             'costs': {'purchase': purchase, 'domestic': '2', 'warehouse': '2.5', 'packaging': '0.5',
                       'sls': sls, 'risk': '1', 'overhead': '1', 'tax': '1.5', 'withdrawal': '0.1'},
             'source': '演示样本 / 非真实市场调研', 'quoteValidUntil': expiry,
             'checks': {'supply': True, 'logistics': bool(weight), 'rights': i != 7, 'compliance': True, 'facts': True},
             'facts': {'material': material, 'size': size, 'pack': pack, 'use': ''},
             'demo': True, 'revision': 1, 'createdAt': datetime.now(timezone.utc).isoformat(), 'approval': None, 'content': None}
        products.append(p)
    return products
