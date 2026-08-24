#!/usr/bin/env python3
"""生成「悦己 YUEJI 美妆」模拟数据：40款产品 / 180条FAQ / 10条售后政策。

运行：python scripts/gen_data.py
输出：data/raw/products.json, faq.jsonl, policies.json
数据为合成数据（灵感来自真实产品，避免版权问题）。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from config import settings

random.seed(42)

BRAND = "悦己 YUEJI"

# ============================================================
# 一、40 款产品（4 品类 × 10）
# ============================================================
# 字段：name, category, spec, price, original_price, ingredients,
#       efficacy, skin_types, skin_issues, age_groups, usage, cautions,
#       shelf_life, stock, monthly_sales, rating, tags
P = []

# ---------- 洁面 ----------
P += [
    dict(name="氨基酸温和洁面乳", category="洁面", spec="120g", price=69, original_price=89,
         ingredients=["月桂酰谷氨酸钠", "氨基酸表活", "甘油", "泛醇"],
         efficacy=["温和清洁", "保湿"], skin_types=["干性", "敏感性"], skin_issues=["干燥起皮", "敏感泛红"],
         age_groups=["18-25", "26-35", "36+"], usage="湿脸后取适量揉出泡沫，打圈按摩30秒后清水洗净",
         cautions="避免入眼；皮肤破损处慎用", shelf_life="36个月", stock=1200, monthly_sales=8900, rating=4.8,
         tags=["氨基酸", "温和", "敏感肌"]),
    dict(name="净澈控油洁面啫喱", category="洁面", spec="150ml", price=79, original_price=99,
         ingredients=["椰油酰甘氨酸钾", "薄荷醇", "PCA锌", "茶树提取物"],
         efficacy=["深层清洁", "控油"], skin_types=["油性", "混合性"], skin_issues=["出油", "毛孔粗大"],
         age_groups=["18-25", "26-35"], usage="湿脸后取适量揉出泡沫，重点清洁T区，清水洗净",
         cautions="敏感肌慎用，含薄荷成分", shelf_life="36个月", stock=800, monthly_sales=7600, rating=4.6,
         tags=["控油", "油皮", "清爽"]),
    dict(name="烟酰胺焕亮洁面膏", category="洁面", spec="100g", price=89, original_price=109,
         ingredients=["烟酰胺", "甘油", "月桂酰谷氨酸钠"],
         efficacy=["清洁", "提亮肤色"], skin_types=["混合性", "油性"], skin_issues=["暗沉", "出油"],
         age_groups=["18-25", "26-35"], usage="湿脸后取适量揉出泡沫，轻柔按摩后洗净",
         cautions="烟酰胺不耐受者建议先局部测试", shelf_life="36个月", stock=650, monthly_sales=5300, rating=4.5,
         tags=["烟酰胺", "提亮"]),
    dict(name="水杨酸祛痘洁面乳", category="洁面", spec="120g", price=95, original_price=119,
         ingredients=["水杨酸(0.5%)", "洋甘菊提取物", "氨基酸表活"],
         efficacy=["清洁", "祛痘", "疏通毛孔"], skin_types=["油性"], skin_issues=["痘痘", "黑头"],
         age_groups=["18-25", "26-35"], usage="湿脸后取适量打圈按摩1分钟，避开眼周，清水洗净，建议晚间使用",
         cautions="含水杨酸，敏感肌慎用；使用后注意防晒", shelf_life="24个月", stock=500, monthly_sales=6100, rating=4.4,
         tags=["祛痘", "水杨酸", "油皮"]),
    dict(name="积雪草舒缓洁面泡沫", category="洁面", spec="200ml", price=99, original_price=129,
         ingredients=["积雪草提取物", "氨基酸表活", "泛醇", "尿囊素"],
         efficacy=["温和清洁", "舒缓修护"], skin_types=["敏感性", "干性"], skin_issues=["敏感泛红", "干燥起皮"],
         age_groups=["18-25", "26-35", "36+"], usage="按压2泵泡沫直接上脸，轻柔按摩后清水洗净",
         cautions="极干性皮肤使用后及时补水", shelf_life="24个月", stock=900, monthly_sales=7200, rating=4.7,
         tags=["积雪草", "舒缓", "敏感肌", "泡沫"]),
    dict(name="玻尿酸保湿洁面乳", category="洁面", spec="120g", price=75, original_price=95,
         ingredients=["透明质酸钠", "甘油", "神经酰胺NP"],
         efficacy=["温和清洁", "补水保湿"], skin_types=["干性", "中性"], skin_issues=["干燥起皮"],
         age_groups=["18-25", "26-35", "36+"], usage="湿脸后取适量揉出泡沫按摩洗净",
         cautions="无", shelf_life="36个月", stock=1100, monthly_sales=6400, rating=4.6,
         tags=["玻尿酸", "保湿", "干皮"]),
    dict(name="茶多酚净化洁面泥", category="洁面", spec="100g", price=85, original_price=105,
         ingredients=["高岭土", "茶多酚", "芦荟提取物"],
         efficacy=["深层清洁", "吸附油脂", "收敛毛孔"], skin_types=["油性", "混合性"], skin_issues=["黑头", "毛孔粗大", "出油"],
         age_groups=["18-25", "26-35"], usage="湿脸后取适量涂抹全脸（避开眼唇），停留2分钟洗去，每周2-3次",
         cautions="泥状面膜类产品，不宜每日使用", shelf_life="24个月", stock=430, monthly_sales=4800, rating=4.3,
         tags=["清洁泥膜", "黑头", "毛孔"]),
    dict(name="温和卸妆洁面二合一", category="洁面", spec="150ml", price=109, original_price=139,
         ingredients=["癸基葡糖苷", "椰油酰谷氨酸二钠", "维生素E"],
         efficacy=["卸妆", "清洁", "保湿"], skin_types=["干性", "中性", "敏感性"], skin_issues=["干燥起皮", "敏感泛红"],
         age_groups=["18-25", "26-35", "36+"], usage="干手干脸取适量涂抹按摩，加水乳化后清水洗净（浓妆建议先用卸妆油）",
         cautions="防水型彩妆建议配合专用卸妆产品", shelf_life="36个月", stock=760, monthly_sales=5800, rating=4.5,
         tags=["卸妆", "二合一", "温和"]),
    dict(name="美白透亮洁面乳", category="洁面", spec="120g", price=92, original_price=115,
         ingredients=["烟酰胺", "光果甘草提取物", "甘油"],
         efficacy=["清洁", "提亮肤色", "淡化暗沉"], skin_types=["混合性"], skin_issues=["暗沉"],
         age_groups=["18-25", "26-35"], usage="湿脸后取适量揉出泡沫，按摩1分钟后洗净",
         cautions="含烟酰胺，先做耐受测试", shelf_life="36个月", stock=540, monthly_sales=4300, rating=4.4,
         tags=["美白", "烟酰胺", "提亮"]),
    dict(name="男士控油清爽洁面", category="洁面", spec="150ml", price=65, original_price=85,
         ingredients=["薄荷醇", "PCA锌", "活性炭"],
         efficacy=["深层清洁", "控油", "去角质"], skin_types=["油性"], skin_issues=["出油", "黑头"],
         age_groups=["18-25", "26-35"], usage="湿脸后取适量揉出泡沫，重点清洁T区后洗净",
         cautions="含薄荷，敏感肌慎用", shelf_life="36个月", stock=980, monthly_sales=8100, rating=4.5,
         tags=["男士", "控油", "清爽"]),
]

# ---------- 精华 ----------
P += [
    dict(name="烟酰胺焕亮精华液", category="精华", spec="30ml", price=129, original_price=159,
         ingredients=["烟酰胺(5%)", "泛醇", "透明质酸钠"],
         efficacy=["提亮肤色", "淡化痘印", "改善暗沉"], skin_types=["油性", "混合性"], skin_issues=["暗沉", "痘印"],
         age_groups=["18-25", "26-35"], usage="早晚洁面爽肤后取3-4滴，均匀涂抹并轻拍至吸收",
         cautions="烟酰胺不耐受者先局部测试；白天使用需防晒", shelf_life="36个月", stock=1560, monthly_sales=12800, rating=4.8,
         tags=["烟酰胺", "美白", "平价"]),
    dict(name="玻尿酸保湿精华液", category="精华", spec="30ml", price=119, original_price=149,
         ingredients=["多重玻尿酸", "泛醇", "甘油"],
         efficacy=["深层补水", "锁水保湿"], skin_types=["干性", "中性", "敏感性"], skin_issues=["干燥起皮"],
         age_groups=["18-25", "26-35", "36+"], usage="爽肤后取2-3滴涂抹全脸，可叠加面霜锁水",
         cautions="无", shelf_life="36个月", stock=1700, monthly_sales=10200, rating=4.7,
         tags=["玻尿酸", "补水", "干皮"]),
    dict(name="视黄醇抗皱精华", category="精华", spec="30ml", price=189, original_price=239,
         ingredients=["视黄醇(0.3%)", "角鲨烷", "神经酰胺NP"],
         efficacy=["抗皱", "紧致", "平滑细纹"], skin_types=["干性", "中性"], skin_issues=["细纹"],
         age_groups=["26-35", "36+"], usage="仅夜间使用，洁面后取2-3滴，避光保存；初期隔天使用建立耐受",
         cautions="孕妇禁用；白天必须防晒；初期可能脱皮属正常", shelf_life="24个月", stock=420, monthly_sales=3900, rating=4.5,
         tags=["视黄醇", "抗老", "A醇"]),
    dict(name="积雪草修护精华液", category="精华", spec="30ml", price=139, original_price=169,
         ingredients=["积雪草提取物", "泛醇", "甘草酸二钾"],
         efficacy=["舒缓修护", "褪红", "强韧屏障"], skin_types=["敏感性", "干性"], skin_issues=["敏感泛红", "干燥起皮"],
         age_groups=["18-25", "26-35", "36+"], usage="洁面后取2-3滴轻拍全脸，泛红处可叠加",
         cautions="无", shelf_life="36个月", stock=880, monthly_sales=6900, rating=4.8,
         tags=["积雪草", "修护", "敏感肌", "褪红"]),
    dict(name="水杨酸净痘精华", category="精华", spec="20ml", price=99, original_price=129,
         ingredients=["水杨酸(2%)", "烟酰胺", "金缕梅提取物"],
         efficacy=["祛痘", "疏通毛孔", "控油"], skin_types=["油性"], skin_issues=["痘痘", "黑头"],
         age_groups=["18-25"], usage="点涂于痘痘处，早晚各一次；全脸使用每周2-3次",
         cautions="含水杨酸，敏感肌慎用；避免与A醇同用；注意防晒", shelf_life="24个月", stock=930, monthly_sales=8800, rating=4.4,
         tags=["祛痘", "水杨酸", "油皮"]),
    dict(name="维生素C焕肤精华", category="精华", spec="30ml", price=159, original_price=199,
         ingredients=["抗坏血酸(10%)", "维生素E", "阿魏酸"],
         efficacy=["提亮肤色", "抗氧化", "淡化色斑"], skin_types=["干性", "中性", "混合性"], skin_issues=["暗沉"],
         age_groups=["26-35", "36+"], usage="晨间洁面后取3滴涂抹，后续必须防晒；开封后2个月内用完",
         cautions="高浓度VC初次使用可能有刺痛；避光保存", shelf_life="24个月", stock=610, monthly_sales=5200, rating=4.6,
         tags=["维C", "抗氧化", "提亮"]),
    dict(name="二裂酵母修护精华", category="精华", spec="50ml", price=219, original_price=269,
         ingredients=["二裂酵母发酵产物滤液", "泛醇", "玻尿酸"],
         efficacy=["修护屏障", "维稳", "抗初老"], skin_types=["干性", "混合性", "敏感性"], skin_issues=["干燥起皮", "敏感泛红"],
         age_groups=["26-35", "36+"], usage="早晚洁面后取2-3滴涂抹全脸",
         cautions="无", shelf_life="24个月", stock=720, monthly_sales=6100, rating=4.7,
         tags=["二裂酵母", "维稳", "修护"]),
    dict(name="神经酰胺屏障精华", category="精华", spec="30ml", price=149, original_price=179,
         ingredients=["神经酰胺NP", "神经酰胺AP", "角鲨烷"],
         efficacy=["修护屏障", "保湿", "舒缓"], skin_types=["敏感性", "干性"], skin_issues=["敏感泛红", "干燥起皮"],
         age_groups=["18-25", "26-35", "36+"], usage="洁面后取2-3滴涂抹，可与其他精华叠加",
         cautions="无", shelf_life="36个月", stock=840, monthly_sales=5900, rating=4.6,
         tags=["神经酰胺", "屏障修护", "敏感肌"]),
    dict(name="虾青素抗氧化精华", category="精华", spec="30ml", price=169, original_price=209,
         ingredients=["虾青素", "烟酰胺", "维生素E"],
         efficacy=["抗氧化", "提亮", "抗初老"], skin_types=["混合性", "油性"], skin_issues=["暗沉"],
         age_groups=["26-35", "36+"], usage="早晚洁面后取3滴涂抹全脸",
         cautions="含虾青素呈淡橙色属正常；白天配合防晒", shelf_life="24个月", stock=380, monthly_sales=3400, rating=4.5,
         tags=["虾青素", "抗氧化"]),
    dict(name="多肽紧致精华液", category="精华", spec="30ml", price=199, original_price=249,
         ingredients=["棕榈酰五肽-4", "乙酰基六肽-8", "玻尿酸"],
         efficacy=["紧致", "淡化细纹", "提升轮廓"], skin_types=["干性", "中性"], skin_issues=["细纹"],
         age_groups=["26-35", "36+"], usage="早晚洁面后取2-3滴，由下往上提拉涂抹",
         cautions="无", shelf_life="36个月", stock=460, monthly_sales=4100, rating=4.6,
         tags=["多肽", "紧致", "抗老"]),
]

# ---------- 水乳 ----------
P += [
    dict(name="玻尿酸水润水乳套装", category="水乳", spec="水150ml+乳120ml", price=169, original_price=219,
         ingredients=["多重玻尿酸", "甘油", "神经酰胺NP"],
         efficacy=["补水", "保湿", "锁水"], skin_types=["干性", "中性"], skin_issues=["干燥起皮"],
         age_groups=["18-25", "26-35", "36+"], usage="洁面后先拍水再涂乳，早晚使用",
         cautions="无", shelf_life="36个月", stock=1350, monthly_sales=9800, rating=4.7,
         tags=["水乳套装", "玻尿酸", "干皮"]),
    dict(name="控油平衡水乳套装", category="水乳", spec="水150ml+乳120ml", price=159, original_price=199,
         ingredients=["PCA锌", "金缕梅提取物", "烟酰胺"],
         efficacy=["控油", "平衡水油", "收敛毛孔"], skin_types=["油性", "混合性"], skin_issues=["出油", "毛孔粗大"],
         age_groups=["18-25", "26-35"], usage="洁面后先拍水再涂乳，T区可多拍一遍水",
         cautions="含烟酰胺，先做耐受测试", shelf_life="36个月", stock=990, monthly_sales=8700, rating=4.5,
         tags=["控油", "油皮", "水乳"]),
    dict(name="敏感肌舒缓水乳套装", category="水乳", spec="水150ml+乳120ml", price=179, original_price=229,
         ingredients=["积雪草提取物", "泛醇", "甘草酸二钾"],
         efficacy=["舒缓", "褪红", "修护"], skin_types=["敏感性", "干性"], skin_issues=["敏感泛红", "干燥起皮"],
         age_groups=["18-25", "26-35", "36+"], usage="洁面后拍水涂乳，避开破损皮肤",
         cautions="精简护肤，减少叠加", shelf_life="36个月", stock=860, monthly_sales=7600, rating=4.8,
         tags=["敏感肌", "舒缓", "水乳"]),
    dict(name="烟酰胺亮肤水乳套装", category="水乳", spec="水150ml+乳120ml", price=189, original_price=239,
         ingredients=["烟酰胺(水3%/乳4%)", "光果甘草提取物", "玻尿酸"],
         efficacy=["提亮肤色", "改善暗沉", "保湿"], skin_types=["混合性", "油性"], skin_issues=["暗沉"],
         age_groups=["18-25", "26-35"], usage="洁面后先拍水再涂乳，早晚使用",
         cautions="烟酰胺不耐受者先局部测试；白天注意防晒", shelf_life="36个月", stock=780, monthly_sales=7100, rating=4.6,
         tags=["烟酰胺", "提亮", "水乳"]),
    dict(name="积雪草修护水乳套装", category="水乳", spec="水150ml+乳120ml", price=175, original_price=215,
         ingredients=["积雪草提取物", "神经酰胺NP", "角鲨烷"],
         efficacy=["修护屏障", "舒缓", "保湿"], skin_types=["敏感性", "干性"], skin_issues=["敏感泛红", "干燥起皮"],
         age_groups=["18-25", "26-35", "36+"], usage="洁面后拍水涂乳，可厚涂乳液做局部修护",
         cautions="无", shelf_life="36个月", stock=640, monthly_sales=5600, rating=4.7,
         tags=["积雪草", "修护", "水乳"]),
    dict(name="神经酰胺屏障水乳套装", category="水乳", spec="水150ml+乳120ml", price=185, original_price=225,
         ingredients=["神经酰胺NP", "神经酰胺AP", "胆甾醇"],
         efficacy=["屏障修护", "保湿", "维稳"], skin_types=["干性", "敏感性"], skin_issues=["干燥起皮", "敏感泛红"],
         age_groups=["26-35", "36+"], usage="洁面后拍水涂乳，早晚使用",
         cautions="无", shelf_life="36个月", stock=520, monthly_sales=4700, rating=4.6,
         tags=["神经酰胺", "屏障", "水乳"]),
    dict(name="玫瑰精粹保湿水乳套装", category="水乳", spec="水150ml+乳120ml", price=199, original_price=249,
         ingredients=["玫瑰提取物", "玻尿酸", "甘油"],
         efficacy=["补水", "提亮", "香氛体验"], skin_types=["干性", "中性"], skin_issues=["干燥起皮"],
         age_groups=["18-25", "26-35"], usage="洁面后拍水涂乳，早晚使用",
         cautions="含香精，极敏感肌慎用", shelf_life="36个月", stock=450, monthly_sales=3900, rating=4.5,
         tags=["玫瑰", "保湿", "香氛"]),
    dict(name="茶树祛痘水乳套装", category="水乳", spec="水150ml+乳120ml", price=165, original_price=205,
         ingredients=["茶树提取物", "水杨酸", "烟酰胺"],
         efficacy=["祛痘", "控油", "舒缓"], skin_types=["油性"], skin_issues=["痘痘", "出油"],
         age_groups=["18-25"], usage="洁面后拍水涂乳，痘痘处可湿敷爽肤水",
         cautions="含水杨酸，敏感肌慎用；注意防晒", shelf_life="24个月", stock=590, monthly_sales=5400, rating=4.4,
         tags=["茶树", "祛痘", "水乳"]),
    dict(name="男士控油水乳套装", category="水乳", spec="水150ml+乳120ml", price=149, original_price=189,
         ingredients=["PCA锌", "薄荷醇", "玻尿酸"],
         efficacy=["控油", "保湿", "清爽"], skin_types=["油性"], skin_issues=["出油"],
         age_groups=["18-25", "26-35"], usage="洁面后拍水涂乳，早晚使用",
         cautions="含薄荷，敏感肌慎用", shelf_life="36个月", stock=1050, monthly_sales=8200, rating=4.5,
         tags=["男士", "控油", "水乳"]),
    dict(name="胶原蛋白弹润水乳套装", category="水乳", spec="水150ml+乳120ml", price=209, original_price=259,
         ingredients=["水解胶原", "多肽", "玻尿酸"],
         efficacy=["弹润", "紧致", "保湿"], skin_types=["干性", "中性"], skin_issues=["细纹", "干燥起皮"],
         age_groups=["26-35", "36+"], usage="洁面后拍水涂乳，配合提拉手法",
         cautions="无", shelf_life="36个月", stock=410, monthly_sales=3600, rating=4.6,
         tags=["胶原蛋白", "弹润", "抗老"]),
]

# ---------- 面霜 ----------
P += [
    dict(name="玻尿酸保湿面霜", category="面霜", spec="50g", price=109, original_price=139,
         ingredients=["多重玻尿酸", "角鲨烷", "甘油"],
         efficacy=["深度保湿", "锁水"], skin_types=["干性", "中性"], skin_issues=["干燥起皮"],
         age_groups=["18-25", "26-35", "36+"], usage="精华后取黄豆大小涂全脸，按摩至吸收，早晚使用",
         cautions="无", shelf_life="36个月", stock=1250, monthly_sales=9300, rating=4.7,
         tags=["玻尿酸", "保湿", "干皮"]),
    dict(name="控油清爽凝霜", category="面霜", spec="50g", price=99, original_price=129,
         ingredients=["金缕梅提取物", "PCA锌", "透明质酸钠"],
         efficacy=["控油", "清爽保湿"], skin_types=["油性", "混合性"], skin_issues=["出油"],
         age_groups=["18-25", "26-35"], usage="精华后取适量涂全脸，凝霜质地吸收快",
         cautions="无", shelf_life="36个月", stock=890, monthly_sales=7800, rating=4.5,
         tags=["控油", "凝霜", "油皮"]),
    dict(name="敏感肌修护霜", category="面霜", spec="50g", price=129, original_price=159,
         ingredients=["积雪草提取物", "神经酰胺NP", "角鲨烷", "尿囊素"],
         efficacy=["修护屏障", "舒缓", "褪红"], skin_types=["敏感性", "干性"], skin_issues=["敏感泛红", "干燥起皮"],
         age_groups=["18-25", "26-35", "36+"], usage="精华后取适量厚涂于泛红干燥处，轻柔按摩吸收",
         cautions="无", shelf_life="36个月", stock=760, monthly_sales=6500, rating=4.8,
         tags=["敏感肌", "修护", "舒缓"]),
    dict(name="烟酰胺亮肤面霜", category="面霜", spec="50g", price=119, original_price=149,
         ingredients=["烟酰胺(4%)", "光果甘草提取物", "玻尿酸"],
         efficacy=["提亮肤色", "改善暗沉", "保湿"], skin_types=["混合性"], skin_issues=["暗沉"],
         age_groups=["18-25", "26-35"], usage="精华后取适量涂全脸，早晚使用",
         cautions="烟酰胺不耐受者先局部测试；白天防晒", shelf_life="36个月", stock=680, monthly_sales=5900, rating=4.5,
         tags=["烟酰胺", "提亮", "面霜"]),
    dict(name="视黄醇抗皱晚霜", category="面霜", spec="50g", price=169, original_price=209,
         ingredients=["视黄醇(0.2%)", "神经酰胺NP", "角鲨烷"],
         efficacy=["抗皱", "紧致", "夜间修护"], skin_types=["干性", "中性"], skin_issues=["细纹"],
         age_groups=["26-35", "36+"], usage="仅夜间使用，精华后取适量涂全脸，避光保存",
         cautions="孕妇禁用；初期隔天使用建立耐受；白天严格防晒", shelf_life="24个月", stock=470, monthly_sales=4400, rating=4.5,
         tags=["视黄醇", "抗老", "晚霜"]),
    dict(name="神经酰胺修护霜", category="面霜", spec="50g", price=115, original_price=145,
         ingredients=["神经酰胺NP", "神经酰胺AP", "胆甾醇", "角鲨烷"],
         efficacy=["屏障修护", "保湿", "维稳"], skin_types=["敏感性", "干性"], skin_issues=["干燥起皮", "敏感泛红"],
         age_groups=["18-25", "26-35", "36+"], usage="精华后取适量涂全脸，早晚使用",
         cautions="无", shelf_life="36个月", stock=820, monthly_sales=6100, rating=4.7,
         tags=["神经酰胺", "屏障", "修护"]),
    dict(name="清爽保湿啫喱霜", category="面霜", spec="50g", price=95, original_price=125,
         ingredients=["玻尿酸", "芦荟提取物", "甘油"],
         efficacy=["补水", "清爽保湿"], skin_types=["油性", "混合性"], skin_issues=["出油", "干燥起皮"],
         age_groups=["18-25", "26-35"], usage="精华后取适量涂全脸，啫喱质地适合夏季",
         cautions="无", shelf_life="36个月", stock=700, monthly_sales=5400, rating=4.4,
         tags=["啫喱", "清爽", "保湿"]),
    dict(name="多肽紧致面霜", category="面霜", spec="50g", price=189, original_price=239,
         ingredients=["棕榈酰五肽-4", "乙酰基六肽-8", "角鲨烷"],
         efficacy=["紧致", "淡化细纹", "提升轮廓"], skin_types=["干性", "中性"], skin_issues=["细纹"],
         age_groups=["26-35", "36+"], usage="精华后取适量由下往上提拉涂抹",
         cautions="无", shelf_life="36个月", stock=390, monthly_sales=3300, rating=4.6,
         tags=["多肽", "紧致", "抗老"]),
    dict(name="美白淡斑霜", category="面霜", spec="50g", price=179, original_price=229,
         ingredients=["烟酰胺", "光果甘草提取物", "维生素C衍生物"],
         efficacy=["美白", "淡化色斑", "提亮"], skin_types=["混合性", "干性"], skin_issues=["暗沉"],
         age_groups=["26-35", "36+"], usage="精华后取适量涂抹于色斑处并全脸使用，早晚各一次",
         cautions="含烟酰胺与VC衍生物，先做耐受测试；白天防晒", shelf_life="36个月", stock=440, monthly_sales=4100, rating=4.5,
         tags=["美白", "淡斑", "烟酰胺"]),
    dict(name="男士保湿面霜", category="面霜", spec="50g", price=89, original_price=119,
         ingredients=["玻尿酸", "甘油", "维生素E"],
         efficacy=["保湿", "锁水"], skin_types=["油性", "混合性"], skin_issues=["干燥起皮", "出油"],
         age_groups=["18-25", "26-35"], usage="洁面后取适量涂全脸，早晚使用",
         cautions="无", shelf_life="36个月", stock=900, monthly_sales=7100, rating=4.4,
         tags=["男士", "保湿", "面霜"]),
]

# 编号与补全
for i, p in enumerate(P):
    p["product_id"] = f"P{i + 1:03d}"
    p["brand"] = BRAND
    p.setdefault("stock", 500)
    p.setdefault("monthly_sales", 5000)
    p.setdefault("rating", 4.5)
    p.setdefault("shelf_life", "36个月")
    p.setdefault("cautions", "无")
    p.setdefault("faq_ids", [])

# ============================================================
# 二、FAQ（人工核心 60 条 + 自动按产品生成 120 条 = 180 条）
# ============================================================
FAQ = []


def add_faq(category: str, q: str, a: str, source: str = "", aliases: list[str] | None = None) -> None:
    FAQ.append({
        "faq_id": f"F{len(FAQ) + 1:03d}",
        "category": category,
        "question": q,
        "answer": a,
        "source": source,
        "aliases": aliases or [],
    })


# ---- 通用/品牌（8） ----
add_faq("通用", "你们是什么品牌？", "我们是国货美妆品牌「悦己 YUEJI」，主打高性价比的护肤产品，全系列不添加酒精、色素，成分公开透明。", aliases=["品牌", "介绍", "你们是谁"])
add_faq("通用", "产品在哪里生产？", "我们的产品由国内通过 ISO22716 认证的工厂生产，每一批次都经过第三方检测，可放心使用。", aliases=["产地", "生产", "工厂"])
add_faq("通用", "产品是正品吗？", "我们只在官方渠道销售，支持专柜验货，每件产品都有防伪码，可扫码验证真伪。", aliases=["正品", "真假", "防伪"])
add_faq("通用", "如何联系人工客服？", "您可以直接回复「人工」，或拨打客服热线 400-888-0000（工作日 9:00-21:00），我们会尽快为您服务。", aliases=["人工", "客服", "电话"])
add_faq("通用", "你们支持什么付款方式？", "支持支付宝、微信支付、银行卡以及花呗分期（3/6/12期免息，限指定商品）。", aliases=["付款", "支付", "花呗"])
add_faq("通用", "有哪些发货渠道？", "全国大部分地区由顺丰或中通发货，偏远地区 EMS 发货，均支持物流跟踪。", aliases=["快递", "发货渠道"])
add_faq("通用", "产品可以退换吗？", "支持7天无理由退换货，具体规则可回复「售后政策」查看详情。", aliases=["退换", "退货"])
add_faq("通用", "使用产品后过敏怎么办？", "如使用后出现过敏反应，请立即停用并联系人工客服，我们会协助您走质量问题售后流程，凭医院诊断可全额退款。", aliases=["过敏", "不良反应"])

# ---- 商品-成分/功效（18） ----
add_faq("商品-成分", "烟酰胺有什么作用？", "烟酰胺是维生素B3衍生物，主要作用是抑制黑色素转运、提亮肤色、淡化痘印，同时兼具控油和修护屏障的作用，浓度一般在2%-5%。", aliases=["烟酰胺", "b3", "vb3"])
add_faq("商品-成分", "烟酰胺需要建立耐受吗？", "需要。建议第一周隔天使用、每次少量，观察皮肤反应；如出现刺痛泛红，先减少频率，配合修护类产品过渡，一般1-2周可建立耐受。", aliases=["耐受", "刺痛", "泛红"])
add_faq("商品-成分", "玻尿酸和透明质酸钠是同一个东西吗？", "是的，透明质酸钠就是玻尿酸的盐形式，更稳定易吸收，主要作用是抓取水分、深层补水。", aliases=["玻尿酸", "透明质酸"])
add_faq("商品-成分", "视黄醇（A醇）有什么注意事项？", "视黄醇是高效抗老成分，但刺激性较强：①仅夜间使用 ②初期隔天使用建立耐受 ③孕妇禁用 ④白天必须严格防晒 ⑤避免与水杨酸等猛药叠加。", aliases=["视黄醇", "A醇", "retinol"])
add_faq("商品-成分", "水杨酸适合什么皮肤？", "水杨酸是脂溶性酸，能深入毛孔溶解油脂，适合油性、痘痘肌，对黑头闭口效果好；敏感肌和干皮慎用，使用后注意防晒。", aliases=["水杨酸", "bha", "酸类"])
add_faq("商品-成分", "积雪草有什么功效？", "积雪草提取物主打舒缓修护、褪红抗炎，是敏感肌的经典成分，能帮助强韧皮肤屏障、缓解泛红。", aliases=["积雪草", "centella"])
add_faq("商品-成分", "神经酰胺的作用是什么？", "神经酰胺是皮肤屏障的重要组成部分，像「砖墙」中的水泥，补充神经酰胺能修护屏障、减少水分流失、缓解干燥敏感。", aliases=["神经酰胺", "ceramide", "屏障"])
add_faq("商品-成分", "维生素C白天能用吗？", "可以用，但必须搭配防晒。VC是抗氧化成分，白天用能帮助抵御紫外线损伤，但本身不稳定，建议选衍生物配方或做好避光保存。", aliases=["维C", "vc", "抗坏血酸"])
add_faq("商品-成分", "成分表里有酒精吗？", "我们全系列产品不添加酒精（乙醇），敏感肌可放心选择。", aliases=["酒精", "乙醇"])
add_faq("商品-成分", "孕妇可以用视黄醇吗？", "不可以。视黄醇（A醇）类成分孕妇禁用，建议孕期选择成分简单的保湿修护类产品，如我们的玻尿酸保湿系列。", aliases=["孕妇", "孕期", "哺乳期"])
add_faq("商品-成分", "成分表怎么看是否适合自己？", "核心看三点：①有没有过敏成分（对照自己已知过敏原）②功效成分浓度（排位越靠前浓度越高）③是否含刺激性成分（酸类/A醇需要耐受）。", aliases=["成分表", "怎么看成分"])
add_faq("商品-成分", "敏感肌可以用烟酰胺吗？", "可以尝试，但必须从低浓度开始建立耐受。建议先用我们的积雪草修护系列稳定屏障后，再逐步尝试含烟酰胺的产品。", aliases=["敏感肌", "烟酰胺", "耐受"])
add_faq("商品-成分", "油皮需要补水吗？", "需要。出油不代表不缺水的，油皮往往是「外油内干」，选择清爽质地的保湿产品（如控油清爽凝霜）平衡水油即可。", aliases=["油皮", "补水", "外油内干"])
add_faq("商品-成分", "祛痘产品多久见效？", "水杨酸类祛痘产品一般连续使用2-4周可见改善，但祛痘是系统工程，需配合饮食作息；严重痤疮请及时就医。", aliases=["祛痘", "多久见效"])
add_faq("商品-成分", "美白产品多久见效？", "皮肤代谢周期约28天，美白产品一般坚持使用4-8周可见肤色提亮；同时必须做好防晒，否则效果会打折扣。", aliases=["美白", "多久见效", "28天"])
add_faq("商品-成分", "精华和面霜可以一起用吗？", "可以。护肤顺序是：洁面→水→精华→乳液/面霜。精华负责针对性功效（美白/抗老），面霜负责最后锁水保湿。", aliases=["精华", "面霜", "顺序", "叠加"])
add_faq("商品-成分", "早C晚A是什么？", "早C晚A是经典护肤搭配：早晨用维生素C抗氧化抵御日间损伤，晚上用A醇（视黄醇）抗老修护。注意A醇需建立耐受并严格防晒。", aliases=["早c晚a", "护肤搭配"])
add_faq("商品-成分", "怎么判断自己是敏感肌？", "敏感肌典型表现：换季易泛红、用护肤品易刺痛、皮肤薄可见红血丝。建议先精简护肤，选用积雪草/神经酰胺类修护产品观察2周。", aliases=["敏感肌", "怎么判断"])

# ---- 商品-使用（12） ----
add_faq("商品-使用", "护肤的正确步骤是什么？", "日间：洁面→爽肤水→精华→乳液/面霜→防晒。夜间：卸妆→洁面→爽肤水→精华→乳液/面霜（A醇类夜间专用）。", aliases=["步骤", "顺序", "怎么护肤"])
add_faq("商品-使用", "精华液一次用多少？", "一般3-4滴即可涂全脸，过多不易吸收还容易闷痘；质地清爽的可适当加量至5滴。", aliases=["用量", "几滴"])
add_faq("商品-使用", "面膜可以天天敷吗？", "不建议。贴片面膜每周2-3次即可，天天敷容易过度水合损伤屏障；清洁泥膜每周1-2次。", aliases=["面膜", "频率"])
add_faq("商品-使用", "水乳套装先用水还是先乳？", "先水后乳：爽肤水二次清洁+打开吸收通道，乳液锁水保湿。也可用「先乳后水」的日系方法，但绝大多数产品推荐先水后乳。", aliases=["先水", "先乳", "顺序"])
add_faq("商品-使用", "洁面产品需要早晚都用吗？", "建议早晚各一次：早间温和清洁夜间代谢物，晚间彻底清洁彩妆和防晒。敏感肌早晨可用清水或极温和洁面。", aliases=["洁面", "早晚", "频率"])
add_faq("商品-使用", "护肤品开封后能用多久？", "护肤品包装上都有开盖保质期标识（如 6M/12M），即开盖后建议在6/12个月内用完；VC类活性产品建议2-3个月内用完。", aliases=["开封", "保质期", "6m"])
add_faq("商品-使用", "可以先涂防晒再涂面霜吗？", "不可以。顺序是护肤（面霜）后最后一步涂防晒，防晒霜需要成膜，涂在护肤最后一步才能发挥效果。", aliases=["防晒", "顺序"])
add_faq("商品-使用", "用完护肤品搓泥怎么办？", "搓泥常见原因：前序产品未吸收就叠加、产品叠加过多、含高分子成分。建议：每步等30秒吸收再下一步，减少叠加种类。", aliases=["搓泥", "不吸收"])
add_faq("商品-使用", "护肤品可以涂在眼周吗？", "一般避开眼周，眼周皮肤更薄更敏感，建议使用专门眼霜；如产品标注「可用于眼周」则无妨。", aliases=["眼周", "眼霜"])
add_faq("商品-使用", "精华和原液有什么区别？", "原液是单一高浓度成分（如玻尿酸原液），精华是多种成分复配。原液更「纯粹」，精华更「全面」，可以按需选择。", aliases=["原液", "精华", "区别"])
add_faq("商品-使用", "刷酸后需要停用其他护肤品吗？", "刷酸（水杨酸/果酸）期间建议精简护肤：停用A醇、去角质等刺激性产品，只用温和洁面+修护保湿，并严格防晒。", aliases=["刷酸", "停用"])
add_faq("商品-使用", "护肤品要放冰箱保存吗？", "一般常温避光保存即可；夏季高温时，VC类等活性产品可放冰箱冷藏层（非冷冻），但注意取出回温再使用。", aliases=["冰箱", "保存"])

# ---- 订单（18） ----
add_faq("订单", "如何查询我的订单？", "请提供您的订单号和下单手机号后四位，我会帮您查询订单状态和物流信息。", aliases=["查订单", "订单号", "我的订单"])
add_faq("订单", "下单后多久发货？", "现货商品48小时内发货（工作日），预售商品按页面标注的发货时间发货，发货后会有短信通知。", aliases=["发货", "多久发货", "现货"])
add_faq("订单", "可以修改订单地址吗？", "未发货订单可在「我的订单-修改地址」中自助修改；已发货订单请联系人工客服尝试拦截修改。", aliases=["改地址", "地址", "修改订单"])
add_faq("订单", "可以取消订单吗？", "待付款订单可直接取消；待发货订单可在订单页申请取消，审核通过后原路退款；已发货订单需等签收后走退货流程。", aliases=["取消订单", "退款", "不想要"])
add_faq("订单", "订单显示待付款怎么办？", "待付款表示订单还未支付成功，请在支付页面30分钟内完成支付，超时订单会自动关闭，可重新下单。", aliases=["待付款", "支付", "没付钱"])
add_faq("订单", "下单后没有收到短信怎么办？", "请先检查手机拦截短信，或联系人工客服核对下单手机号；也可直接提供订单号让我帮您查询。", aliases=["短信", "没收到"])
add_faq("订单", "怎么开发票？", "下单后30天内可在「我的订单-申请发票」中填写开票信息，电子发票将在7个工作日内发送至邮箱。", aliases=["发票", "开票"])
add_faq("订单", "可以合并订单发货吗？", "同一账户多笔订单无法自动合并，如需合并可联系人工客服在未发货前协助处理。", aliases=["合并", "一起发货"])
add_faq("订单", "订单被拆分发货是怎么回事？", "多件商品可能分仓发货，物流会拆分为多个包裹，属于正常情况，请以各包裹物流信息为准。", aliases=["拆分", "分开发货"])
add_faq("订单", "怎么确认收货？", "签收后可在「我的订单」中点击确认收货；系统也会在签收后7天自动确认收货。", aliases=["确认收货", "签收"])
add_faq("订单", "优惠券下单后可以补用吗？", "优惠券需在支付前使用，下单后无法补用；如订单未支付，可取消后重新下单使用优惠券。", aliases=["优惠券", "补用"])
add_faq("订单", "下单时忘记用积分了怎么办？", "积分抵扣需在支付前使用；如订单未支付可取消重下，已支付订单无法补用积分。", aliases=["积分", "抵扣"])
add_faq("订单", "可以用两个账号下单吗？", "可以，但部分限购活动商品每个账号限购1件，请以活动规则为准。", aliases=["限购", "多账号"])
add_faq("订单", "订单里的赠品没收到怎么办？", "请提供订单号联系人工客服核实，赠品与正品分开发货时可能存在时间差，确认漏发后会为您补发。", aliases=["赠品", "漏发"])
add_faq("订单", "购买多件会有优惠吗？", "店铺部分商品支持满减和「多件多折」活动，具体以商品页活动标签为准，下单前可先咨询。", aliases=["多件", "满减", "优惠"])
add_faq("订单", "订单状态有哪些？", "订单状态分为：待付款、待发货、已发货、已完成、已取消、退款中，您可随时提供订单号让我帮您查询最新状态。", aliases=["状态", "订单状态"])
add_faq("订单", "收货后发现少件怎么办？", "请保留快递面单和开箱视频，提供订单号联系人工客服，核实后会免费补发或按错发漏发流程处理。", aliases=["少件", "缺件"])
add_faq("订单", "订单可以指定快递吗？", "目前不支持指定快递公司，默认根据收货地址智能分配顺丰或中通，均为正规快递。", aliases=["指定快递", "顺丰"])

# ---- 物流（14） ----
add_faq("物流", "快递一般几天能到？", "现货商品48小时内发货，发货后顺丰1-3天、中通2-4天送达（偏远地区3-7天），大促期间可能延迟1-2天。", aliases=["几天到", "时效", "多久到"])
add_faq("物流", "怎么查物流？", "请提供订单号和手机尾号，我可以帮您查询最新物流动态；也可以在小程序「我的订单-物流详情」自助查询。", aliases=["查物流", "物流", "快递到哪"])
add_faq("物流", "物流好几天不更新怎么办？", "物流信息超过48小时未更新可能是在中转站，请提供订单号，我帮您核实并联系快递催促。", aliases=["不更新", "卡住", "物流不动"])
add_faq("物流", "可以改快递地址吗？", "未发货订单可改地址；已发货订单在快递派送前可联系人工客服尝试改派，中转后无法修改。", aliases=["改地址", "派送"])
add_faq("物流", "快递显示签收但我没收到怎么办？", "请先检查家人/前台/快递柜是否代收，若确实未收到，请提供订单号，我们会在24小时内联系快递核实处理。", aliases=["签收没收到", "没收到快递"])
add_faq("物流", "快递到了可以放快递柜吗？", "派送前快递员会电话确认，您可指定放快递柜或驿站；超时未取会被退回，请及时取件。", aliases=["快递柜", "驿站", "代收"])
add_faq("物流", "大促期间物流会慢吗？", "大促高峰期订单量激增，发货和运输可能延迟1-3天，我们会尽力保障时效，感谢理解。", aliases=["大促", "双11", "延迟"])
add_faq("物流", "可以加急发货吗？", "现货商品默认48小时内发货，如需加急可联系人工客服看能否优先出库，无法保证一定成功。", aliases=["加急", "优先发货"])
add_faq("物流", "为什么有两个物流单号？", "多件商品分仓发货会产生多个单号，属于正常情况，请分别跟踪每个包裹。", aliases=["两个单号", "多包裹"])
add_faq("物流", "偏远地区多久能到？", "新疆、西藏、内蒙古等偏远地区一般3-7天送达，具体以物流信息为准。", aliases=["偏远", "新疆", "西藏"])
add_faq("物流", "物流显示拒收是怎么回事？", "拒收通常是因为收件人未接电话或主动拒收，包裹会退回仓库，退款将在签收退货后处理。", aliases=["拒收", "退回"])
add_faq("物流", "可以拦截快递吗？", "已发货订单如需拦截，请尽快联系人工客服，中转前可尝试拦截改址；拦截失败需等退回后再处理退款。", aliases=["拦截", "截单"])
add_faq("物流", "快递被退回怎么办？", "因拒收或超时未取被退回的包裹，仓库签收后会为您办理退款或重新发货（运费自理除外）。", aliases=["退回", "退件"])
add_faq("物流", "节假日发货吗？", "法定节假日期间发货和物流时效会顺延，节后按订单顺序发货，具体以物流信息为准。", aliases=["节假日", "春节", "国庆"])

# ---- 售后（20） ----
add_faq("售后", "支持七天无理由退换吗？", "支持。签收后7天内（含）未使用、不影响二次销售的商品可申请无理由退货退款，运费由买家承担（质量问题除外）。", aliases=["七天", "无理由", "退换"])
add_faq("售后", "退货流程是怎样的？", "退货流程：联系客服提交申请→审核通过（1-3个工作日）→寄回商品（附赠品）→仓库验货（1-3天）→退款原路返回（3-7个工作日）。", aliases=["退货流程", "怎么退"])
add_faq("售后", "质量问题怎么处理？", "签收后30天内如发现质量问题（破损/变质/漏液等），提供照片或视频凭证，核实后免费退换或退款，运费由我们承担。", aliases=["质量问题", "破损", "变质", "漏液"])
add_faq("售后", "错发漏发怎么处理？", "如收到的商品与订单不符（错发/漏发），提供订单号与实物照片，核实后免费补发（顺丰加急），当天处理。", aliases=["错发", "漏发", "发错"])
add_faq("售后", "退货的运费谁承担？", "无理由退货由买家承担运费；质量问题、错发漏发由我们承担运费（支持运费险报销）。", aliases=["运费", "谁出运费"])
add_faq("售后", "退货多久能收到退款？", "仓库验货通过后，退款将在3-7个工作日内原路返回，具体到账时间以支付渠道为准。", aliases=["退款多久", "什么时候退"])
add_faq("售后", "退货需要寄回赠品吗？", "需要。赠品需随商品一并寄回，如赠品已使用或缺失，会按赠品价值在退款中扣除。", aliases=["赠品", "寄回"])
add_faq("售后", "可以换货吗？", "签收后15天内未使用的商品支持换货（同款同价），质量问题的换货运费由我们承担。", aliases=["换货", "换一件"])
add_faq("售后", "已经使用过的商品可以退吗？", "无理由退货要求未使用、不影响二次销售；已使用商品仅限质量问题可退，其他情况无法退货。", aliases=["用过", "已使用"])
add_faq("售后", "可以仅退款不退货吗？", "仅退款适用于：①订单未发货 ②质量问题且商品无需寄回（我们审核后处理），其他情况需退货退款。", aliases=["仅退款", "不退货"])
add_faq("售后", "退款到哪里？", "退款原路返回至您的支付账户（支付宝/微信/银行卡），花呗支付退回花呗额度。", aliases=["退到哪里", "原路退回"])
add_faq("售后", "超过7天还能退吗？", "超过7天无理由期后，如存在质量问题（30天内）仍可走质量问题售后流程；无质量问题无法退货。", aliases=["超7天", "超期"])
add_faq("售后", "商品破损怎么申请售后？", "请拍摄破损商品照片（含快递面单）并提供订单号，我们会按质量问题流程优先处理，无需等待审核即可安排补发或退款。", aliases=["破损", "碎了", "漏液"])
add_faq("售后", "售后审核需要多久？", "一般1-3个工作日，质量问题凭证齐全可加急至24小时内；大促期间可能延长。", aliases=["审核多久", "审核时间"])
add_faq("售后", "怎么投诉？", "如对服务不满意，可回复「人工」转接投诉专员，或拨打 400-888-0000；我们承诺投诉24小时内响应处理。", aliases=["投诉", "投诉渠道"])
add_faq("售后", "退货影响下次购买吗？", "不影响正常购买；频繁恶意退换会被风控关注，正常售后不会影响账号。", aliases=["影响购买", "黑名单"])
add_faq("售后", "换货运费谁承担？", "无理由换货运费由买家承担；质量问题换货运费由我们承担。", aliases=["换货运费"])
add_faq("售后", "售后申请在哪里提交？", "您可以直接告诉我订单号和售后类型，我帮您在线生成售后工单；也可以在小程序「我的-售后申请」自助提交。", aliases=["售后申请", "提交售后"])
add_faq("售后", "海外可以退货吗？", "目前仅支持中国大陆地区退换货，港澳台及海外订单不支持退货，请下单前确认。", aliases=["海外", "港澳台"])

# ---- 活动/优惠（8） ----
add_faq("活动", "现在有什么优惠活动？", "目前店铺有：新客首单立减20元（无门槛）、满199减30、会员积分抵现，具体以活动页面为准。", aliases=["优惠", "活动", "打折"])
add_faq("活动", "有会员制度吗？", "有。消费即可累积积分，会员等级分为银卡/金卡/黑卡，享95折/9折/85折及生日礼包等权益。", aliases=["会员", "等级", "积分"])
add_faq("活动", "积分有什么用？", "积分可在订单结算时抵扣现金（100积分=1元），也可在积分商城兑换小样和正装。", aliases=["积分", "兑换"])
add_faq("活动", "可以领优惠券吗？", "新客可领20元无门槛券，店铺首页可领满减券（满199减30、满399减80），大促期间券更多。", aliases=["领券", "优惠券"])
add_faq("活动", "会员生日有优惠吗？", "黑卡和金卡会员生日当月可领生日礼包（正装小样+专属折扣券），需提前在会员中心填写生日信息。", aliases=["生日", "生日礼"])
add_faq("活动", "双11有什么活动？", "双11期间全场8折起、满300减100，叠加会员折扣和积分抵现，具体以活动页为准。", aliases=["双11", "双十一", "大促"])
add_faq("活动", "有学生优惠吗？", "学生认证后享95折专属优惠，可与活动叠加（限本人账号），在会员中心完成学生认证即可。", aliases=["学生", "学生优惠"])
add_faq("活动", "优惠券过期了怎么办？", "过期优惠券无法恢复，建议在有效期前使用；关注店铺首页可领新券。", aliases=["优惠券过期", "过期"])

# ---- 自动按产品生成 FAQ（每款 3 条：用法/适用肤质/注意事项）----
for p in P:
    pid = p["product_id"]
    name = p["name"]
    add_faq("商品-使用", f"{name}怎么用？", f"{p['usage']}。规格{p['spec']}，建议早晚按步骤使用，坚持使用效果更佳。", source=pid, aliases=[name, "用法"])
    add_faq("商品-适用", f"{name}适合什么肤质？", f"{name}适合{('、'.join(p['skin_types']))}肤质，主打{('、'.join(p['efficacy'][:3]))}，对{('、'.join(p['skin_issues'][:2]))}有帮助。", source=pid, aliases=[name, "肤质", "适合谁"])
    add_faq("商品-注意", f"{name}有什么注意事项？", f"{p['cautions']}。{('如成分含烟酰胺/视黄醇/水杨酸，请先做耐受测试并注意防晒。' if any(k in p['cautions'] for k in ['烟酰胺', '视黄醇', '水杨酸']) else '敏感肌建议先局部测试。')}", source=pid, aliases=[name, "注意", "禁忌"])

# ============================================================
# 三、售后政策（10 条）
# ============================================================
POLICIES = [
    {"policy_id": "POL-1", "type": "七天无理由", "summary": "签收后7天内（含）未使用、不影响二次销售的商品可无理由退货退款。",
     "rules": {"within_days": 7, "resaleable": True, "unworn": True}, "process": "提交申请→审核→寄回→验货→退款",
     "duration": "审核1-3个工作日，退款原路返回3-7个工作日", "freight": "买家承担（运费险可报销）"},
    {"policy_id": "POL-2", "type": "质量问题", "summary": "签收后30天内发现破损/变质/漏液等质量问题，凭证核实后免费退换或退款。",
     "rules": {"within_days": 30, "quality_issue": True, "evidence_required": ["照片", "视频"]},
     "process": "提交凭证→人工复核（24小时内）→补发/退款", "duration": "复核24小时内", "freight": "商家承担"},
    {"policy_id": "POL-3", "type": "错发漏发", "summary": "收到的商品与订单不符（错发/漏发），核实后免费补发（顺丰加急）。",
     "rules": {"within_days": 30, "mistake": True}, "process": "核对订单与实际收货→免费补发", "duration": "当天处理", "freight": "商家承担"},
    {"policy_id": "POL-4", "type": "换货", "summary": "签收后15天内未使用的商品支持换货（同款同价）。",
     "rules": {"within_days": 15, "resaleable": True}, "process": "提交申请→寄回→换发", "duration": "验货后1-3个工作日换发", "freight": "无理由买家承担，质量问题商家承担"},
    {"policy_id": "POL-5", "type": "仅退款", "summary": "仅适用于订单未发货或质量问题且无需寄回的场景。",
     "rules": {"scenes": ["未发货", "质量问题无需寄回"]}, "process": "提交申请→审核→原路退款", "duration": "未发货即时，质量问题24小时", "freight": "—"},
    {"policy_id": "POL-6", "type": "物流时效", "summary": "现货48小时内发货；顺丰1-3天、中通2-4天（偏远3-7天）。",
     "rules": {"ship_within": "48h", "sf_days": "1-3", "zt_days": "2-4"}, "process": "发货后短信通知+物流跟踪", "duration": "大促顺延1-2天", "freight": "—"},
    {"policy_id": "POL-7", "type": "预售与发货", "summary": "预售商品按页面标注时间发货，发货顺序以支付顺序为准。",
     "rules": {"type": "预售"}, "process": "支付定金→尾款→按序发货", "duration": "以页面标注为准", "freight": "—"},
    {"policy_id": "POL-8", "type": "发票说明", "summary": "下单后30天内可申请电子发票，7个工作日内发送至邮箱。",
     "rules": {"within_days": 30, "type": "电子发票"}, "process": "我的订单-申请发票→填写信息→邮箱查收", "duration": "7个工作日", "freight": "—"},
    {"policy_id": "POL-9", "type": "会员积分", "summary": "消费累积积分（100积分=1元），可抵现或兑换礼品。",
     "rules": {"rate": "消费1元=1积分", "exchange": "100积分=1元"}, "process": "结算时选择积分抵扣", "duration": "积分有效期24个月", "freight": "—"},
    {"policy_id": "POL-10", "type": "价格保护", "summary": "大促活动开始前7天内购买且未发货的商品，可申请差价退补（限同商品同规格）。",
     "rules": {"within_days": 7, "before_ship": True}, "process": "联系客服→核实→差价原路退回", "duration": "核实后24小时", "freight": "—"},
]


def main() -> None:
    settings.ensure_dirs()
    products_path = settings.RAW_DATA_DIR / "products.json"
    faq_path = settings.RAW_DATA_DIR / "faq.jsonl"
    policies_path = settings.RAW_DATA_DIR / "policies.json"

    products_path.write_text(json.dumps(P, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(faq_path, "w", encoding="utf-8") as f:
        for faq in FAQ:
            f.write(json.dumps(faq, ensure_ascii=False) + "\n")
    policies_path.write_text(json.dumps(POLICIES, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ 产品: {len(P)} 款 -> {products_path}")
    print(f"✅ FAQ : {len(FAQ)} 条 -> {faq_path}")
    print(f"✅ 政策: {len(POLICIES)} 条 -> {policies_path}")
    # 质检
    bad = [p for p in P if not p.get("name") or not p.get("ingredients") or not p.get("efficacy")]
    print(f"✅ 质检: 字段完整率 {(1 - len(bad) / len(P)) * 100:.1f}%")
    cats = {}
    for p in P:
        cats[p["category"]] = cats.get(p["category"], 0) + 1
    print(f"✅ 品类分布: {cats}")


if __name__ == "__main__":
    main()
