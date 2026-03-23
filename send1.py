import requests
import json
import time
import argparse
import pandas as pd
from datetime import datetime

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    print("提示：未安装rich库，输出将为文本格式，可执行 pip install rich 优化展示")

# ===================== 核心配置 =====================
CONFIG = {
    "request_timeout": 15,  # 网络请求超时时间（秒）
    "headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://data.eastmoney.com/"
    },
    # 热门板块评分权重（总分100）
    "score_weights": {
        "板块涨幅": 35,  # 集合竞价涨幅权重
        "主力净流入": 40,  # 主力资金流入权重
        "涨跌家数比": 15,  # 上涨家数/下跌家数 权重
        "涨停家数": 10  # 板块内涨停家数权重
    },
    "top_n": 10,  # 默认显示前10个热门板块
    "sckey": "SCT327380TFoQNkVy6gtCe5DGMAjBIx63K"  # 微信推送密钥（必填！）
}


# ===================== 微信推送函数 =====================
def send_wechat_notification(content: str, title: str = "早盘热门板块推送"):
    """
    通过Server酱推送消息到微信
    :param title: 推送标题
    :param content: 推送内容（支持Markdown）
    """
    if not CONFIG["sckey"] or CONFIG["sckey"] == "替换为你的Server酱SCKEY":
        if HAS_RICH:
            console.print("[yellow]⚠️  未配置SCKEY，跳过微信推送[/yellow]")
        else:
            print("⚠️  未配置SCKEY，跳过微信推送")
        return

    try:
        # Server酱Turbo版接口
        url = f"https://sctapi.ftqq.com/{CONFIG['sckey']}.send"
        data = {
            "title": title,
            "desp": content  # desp支持Markdown格式
        }
        response = requests.post(
            url,
            data=data,
            timeout=CONFIG["request_timeout"]
        )
        response.raise_for_status()
        result = response.json()

        if result.get("code") == 0:
            if HAS_RICH:
                console.print("[green]✅ 微信推送成功！[/green]")
            else:
                print("✅ 微信推送成功！")
        else:
            raise Exception(f"推送失败：{result.get('message', '未知错误')}")

    except Exception as e:
        error_msg = f"❌ 微信推送失败：{str(e)}"
        if HAS_RICH:
            console.print(f"[red]{error_msg}[/red]")
        else:
            print(error_msg)


# ===================== 数据抓取函数 =====================
def fetch_board_data(board_type: str) -> pd.DataFrame:
    """
    抓取集合竞价后板块数据
    :param board_type: 板块类型 - "industry"（行业）/ "concept"（概念）
    :return: 包含板块竞价数据的DataFrame
    """
    # 东方财富板块数据接口（适配集合竞价后数据）
    fs_map = {"industry": "m:90+t:2", "concept": "m:90+t:3"}
    url = (
        "https://push2.eastmoney.com/api/qt/clist/get"
        f"?cb=jQuery{int(time.time() * 1000)}"
        "&pn=1&pz=500&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
        "&fltt=2&invt=2&fid=f62"
        f"&fs={fs_map[board_type]}"
        "&fields=f2,f3,f12,f14,f62,f184,f66,f104,f105,f124"
        f"&_={int(time.time() * 1000)}"
    )

    try:
        # 发送请求并解析数据
        response = requests.get(
            url,
            headers=CONFIG["headers"],
            timeout=CONFIG["request_timeout"]
        )
        response.raise_for_status()  # 抛出HTTP错误

        # 处理JSONP格式数据
        raw_data = response.text.strip()
        raw_data = raw_data[raw_data.index("(") + 1: raw_data.rindex(")")]
        json_data = json.loads(raw_data)

        # 提取核心字段
        board_list = []
        for item in json_data["data"]["diff"]:
            board_info = {
                "板块代码": item.get("f12", ""),
                "板块名称": item.get("f14", ""),
                "板块涨幅(%)": round(item.get("f3", 0), 2),  # 集合竞价涨幅
                "主力净流入(亿)": round(item.get("f62", 0) / 1e8, 2),  # 转换为亿
                "上涨家数": item.get("f104", 0),
                "下跌家数": item.get("f105", 0),
                "涨停家数": item.get("f184", 0),  # 板块内涨停家数
                "板块类型": "行业" if board_type == "industry" else "概念"
            }
            board_list.append(board_info)

        # 转换为DataFrame并过滤无效数据
        df = pd.DataFrame(board_list)
        df = df[df["主力净流入(亿)"] >= 0]  # 只保留资金净流入的板块
        return df

    except Exception as e:
        error_msg = f"抓取{board_type}板块数据失败：{str(e)}"
        if HAS_RICH:
            console.print(f"[red]{error_msg}[/red]")
        else:
            print(error_msg)
        return pd.DataFrame()


def fetch_limit_up_stocks() -> pd.DataFrame:
    """
    抓取集合竞价一字板涨停股票数据（包含所属板块）
    :return: 一字板股票数据的DataFrame
    """
    # 东方财富涨停股票接口（适配集合竞价一字板）
    url = (
        "https://push2.eastmoney.com/api/qt/clist/get"
        f"?cb=jQuery{int(time.time() * 1000)}"
        "&pn=1&pz=1000&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
        "&fltt=2&invt=2&fid=f3"
        "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
        "&fields=f2,f3,f12,f14,f20,f21,f86,f87,f102,f128,f136,f137,f138"
        f"&_={int(time.time() * 1000)}"
    )

    try:
        response = requests.get(
            url,
            headers=CONFIG["headers"],
            timeout=CONFIG["request_timeout"]
        )
        response.raise_for_status()

        # 处理JSONP格式数据
        raw_data = response.text.strip()
        raw_data = raw_data[raw_data.index("(") + 1: raw_data.rindex(")")]
        json_data = json.loads(raw_data)

        # 提取一字板股票数据（涨幅=10%左右，且竞价封单为一字板）
        limit_up_list = []
        for item in json_data["data"]["diff"]:
            # 筛选一字板（涨幅≥9.8%，且最新价=涨停价）
            rise = round(item.get("f3", 0), 2)
            if rise >= 9.8:
                stock_info = {
                    "股票代码": item.get("f12", ""),
                    "股票名称": item.get("f14", ""),
                    "涨幅(%)": rise,
                    "最新价": round(item.get("f2", 0), 2),
                    "涨停价": round(item.get("f20", 0), 2),
                    "开盘价": round(item.get("f21", 0), 2),
                    "所属行业板块": item.get("f102", "").split("|")[-1] if item.get("f102") else "",
                    "所属概念板块": item.get("f128", "").split("|")[-1] if item.get("f128") else "",
                    "成交额(万)": round(item.get("f86", 0) / 10000, 2),
                    "成交量(手)": item.get("f87", 0)
                }
                # 确认是一字板（开盘价=涨停价）
                if abs(stock_info["开盘价"] - stock_info["涨停价"]) < 0.01:
                    limit_up_list.append(stock_info)

        # 转换为DataFrame
        df = pd.DataFrame(limit_up_list)
        return df

    except Exception as e:
        error_msg = f"抓取一字板股票数据失败：{str(e)}"
        if HAS_RICH:
            console.print(f"[red]{error_msg}[/red]")
        else:
            print(error_msg)
        return pd.DataFrame()


# ===================== 热门板块评分 =====================
def calculate_hot_board_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算板块热门评分，按总分排序
    :param df: 合并后的行业+概念板块数据
    :return: 带评分的排序后DataFrame
    """
    if df.empty:
        return df

    # 避免除零错误
    df["下跌家数"] = df["下跌家数"].replace(0, 0.1)

    # 1. 计算各维度标准化得分（0-100）
    # 涨幅得分（正向，涨幅越高得分越高）
    max_rise = df["板块涨幅(%)"].max() if df["板块涨幅(%)"].max() > 0 else 1
    df["涨幅得分"] = (df["板块涨幅(%)"] / max_rise) * 100

    # 资金得分（正向，净流入越高得分越高）
    max_flow = df["主力净流入(亿)"].max() if df["主力净流入(亿)"].max() > 0 else 1
    df["资金得分"] = (df["主力净流入(亿)"] / max_flow) * 100

    # 涨跌家数比得分（正向，比值越高得分越高）
    df["涨跌家数比"] = df["上涨家数"] / df["下跌家数"]
    max_ratio = df["涨跌家数比"].max() if df["涨跌家数比"].max() > 0 else 1
    # 修复：先基于涨跌家数比创建涨跌比得分列，而不是引用不存在的列
    df["涨跌比得分"] = (df["涨跌家数比"] / max_ratio) * 100

    # 涨停家数得分（正向，涨停数越高得分越高）
    max_zt = df["涨停家数"].max() if df["涨停家数"].max() > 0 else 1
    df["涨停得分"] = (df["涨停家数"] / max_zt) * 100

    # 2. 计算综合评分（按权重加权）
    df["综合评分"] = (
        df["涨幅得分"] * CONFIG["score_weights"]["板块涨幅"] / 100 +
        df["资金得分"] * CONFIG["score_weights"]["主力净流入"] / 100 +
        df["涨跌比得分"] * CONFIG["score_weights"]["涨跌家数比"] / 100 +
        df["涨停得分"] * CONFIG["score_weights"]["涨停家数"] / 100
    ).round(1)

    # 按综合评分降序排序，保留核心字段
    result_df = df.sort_values("综合评分", ascending=False)[[
        "板块名称", "板块类型", "板块涨幅(%)", "主力净流入(亿)",
        "上涨家数", "下跌家数", "涨停家数", "综合评分"
    ]].reset_index(drop=True)

    return result_df


# ===================== 结果展示 =====================
def display_limit_up_stocks(df: pd.DataFrame):
    """展示竞价一字板股票数据"""
    if df.empty:
        msg = "⚠️  未获取到竞价一字板股票数据"
        if HAS_RICH:
            console.print(f"[yellow]{msg}[/yellow]")
        else:
            print(msg)
        return ""

    # 生成推送内容
    push_content = f"### 🚀 竞价一字板股票（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）\n\n"
    push_content += "| 股票代码 | 股票名称 | 涨幅(%) | 最新价 | 涨停价 | 所属行业板块 | 所属概念板块 |\n"
    push_content += "|----------|----------|---------|--------|--------|--------------|--------------|\n"

    # Rich可视化展示
    if HAS_RICH:
        table = Table(
            title=f"🚀 竞价一字板股票（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）",
            header_style="bold red",
            show_lines=True,
            title_style="bold magenta"
        )
        table.add_column("股票代码", width=10, justify="center")
        table.add_column("股票名称", width=12, style="bold white")
        table.add_column("涨幅(%)", width=8, justify="center", style="red")
        table.add_column("最新价", width=8, justify="center")
        table.add_column("涨停价", width=8, justify="center")
        table.add_column("所属行业板块", width=20)
        table.add_column("所属概念板块", width=20)

        # 填充数据
        for _, row in df.iterrows():
            table.add_row(
                row["股票代码"],
                row["股票名称"],
                str(row["涨幅(%)"]),
                str(row["最新价"]),
                str(row["涨停价"]),
                row["所属行业板块"],
                row["所属概念板块"]
            )
            # 填充推送内容
            push_content += (
                f"| {row['股票代码']} | {row['股票名称']} | {row['涨幅(%)']} | {row['最新价']} | {row['涨停价']} | "
                f"{row['所属行业板块']} | {row['所属概念板块']} |\n"
            )

        console.print(table)
    else:
        # 文本格式展示
        print(f"\n===== 竞价一字板股票（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）=====")
        print(
            f"{'股票代码':<10}{'股票名称':<12}{'涨幅(%)':<8}{'最新价':<8}{'涨停价':<8}{'所属行业板块':<20}{'所属概念板块':<20}")
        print("-" * 80)
        for _, row in df.iterrows():
            print(
                f"{row['股票代码']:<10}{row['股票名称']:<12}{row['涨幅(%)']:<8.2f}{row['最新价']:<8.2f}{row['涨停价']:<8.2f}"
                f"{row['所属行业板块']:<20}{row['所属概念板块']:<20}"
            )
            # 填充推送内容
            push_content += (
                f"| {row['股票代码']} | {row['股票名称']} | {row['涨幅(%)']} | {row['最新价']} | {row['涨停价']} | "
                f"{row['所属行业板块']} | {row['所属概念板块']} |\n"
            )

    push_content += "\n> ⚠️  一字板数据基于集合竞价，开盘后可能变化，仅供参考！"
    return push_content


def display_hot_boards(df: pd.DataFrame, top_n: int):
    """展示热门板块结果"""
    if df.empty:
        msg = "⚠️  未获取到有效板块数据（可能非交易日/网络问题）"
        if HAS_RICH:
            console.print(f"[yellow]{msg}[/yellow]")
        else:
            print(msg)
        return ""

    # 截取前N个热门板块
    df_display = df.head(top_n)

    # 生成推送内容
    push_content = f"### 🔥 早盘集合竞价热门板块（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）\n\n"
    push_content += "| 排名 | 板块名称 | 类型 | 涨幅(%) | 净流入(亿) | 涨跌家数 | 涨停家数 | 综合评分 |\n"
    push_content += "|------|----------|------|---------|------------|----------|----------|----------|\n"

    # Rich可视化展示
    if HAS_RICH:
        table = Table(
            title=f"🔥 早盘集合竞价热门板块（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）",
            header_style="bold cyan",
            show_lines=True,
            title_style="bold yellow"
        )
        # 添加表格列
        table.add_column("排名", width=5, justify="center")
        table.add_column("板块名称", width=15, style="bold white")
        table.add_column("类型", width=6, style="green")
        table.add_column("涨幅(%)", width=8, justify="center")
        table.add_column("净流入(亿)", width=10, justify="right", style="blue")
        table.add_column("涨跌家数", width=12, justify="center")
        table.add_column("涨停家数", width=8, justify="center")
        table.add_column("综合评分", width=8, justify="center", style="magenta")

        # 填充数据
        for idx, (_, row) in enumerate(df_display.iterrows(), 1):
            # 涨幅颜色区分（红涨绿跌）
            rise_color = "green" if row["板块涨幅(%)"] >= 0 else "red"
            rise_text = f"[{rise_color}]{row['板块涨幅(%)']}[/{rise_color}]"

            # 涨跌家数展示
            ratio_text = f"{row['上涨家数']}/{row['下跌家数']}"

            table.add_row(
                str(idx),
                row["板块名称"],
                row["板块类型"],
                rise_text,
                str(row["主力净流入(亿)"]),
                ratio_text,
                str(row["涨停家数"]),
                str(row["综合评分"])
            )

            # 填充推送内容
            push_content += (
                f"| {idx} | {row['板块名称']} | {row['板块类型']} | {row['板块涨幅(%)']} | {row['主力净流入(亿)']} | "
                f"{row['上涨家数']}/{row['下跌家数']} | {row['涨停家数']} | {row['综合评分']} |\n"
            )

        console.print(table)

        # 重点提示面板
        top3 = df_display.head(3)
        tips = "\n📌 开盘重点关注（综合评分TOP3）：\n"
        for i, (_, row) in enumerate(top3.iterrows(), 1):
            tips += f"[{i}] {row['板块名称']}（{row['板块类型']}）- 涨幅{row['板块涨幅(%)']}% | 净流入{row['主力净流入(亿)']}亿 | 涨停{row['涨停家数']}家\n"
        tips += "\n⚠️  数据基于集合竞价，开盘后可能变化，仅供参考！"
        console.print(Panel(tips, border_style="yellow"))

    # 文本格式展示（无rich库）
    else:
        print(f"\n===== 早盘集合竞价热门板块（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）=====")
        print(
            f"{'排名':<5}{'板块名称':<15}{'类型':<6}{'涨幅(%)':<8}{'净流入(亿)':<10}{'涨跌家数':<12}{'涨停家数':<8}{'综合评分':<8}")
        print("-" * 80)
        for idx, (_, row) in enumerate(df_display.iterrows(), 1):
            print(
                f"{idx:<5}{row['板块名称']:<15}{row['板块类型']:<6}{row['板块涨幅(%)']:<8.2f}"
                f"{row['主力净流入(亿)']:<10.2f}{row['上涨家数']}/{row['下跌家数']:<10}{row['涨停家数']:<8}{row['综合评分']:<8.1f}"
            )
            # 填充推送内容
            push_content += (
                f"| {idx} | {row['板块名称']} | {row['板块类型']} | {row['板块涨幅(%)']} | {row['主力净流入(亿)']} | "
                f"{row['上涨家数']}/{row['下跌家数']} | {row['涨停家数']} | {row['综合评分']} |\n"
            )

    # 重点提示
    push_content += "\n### 📌 开盘重点关注（TOP3）\n"
    top3 = df_display.head(3)
    for i, (_, row) in enumerate(top3.iterrows(), 1):
        push_content += f"{i}. {row['板块名称']}（{row['板块类型']}）- 涨幅{row['板块涨幅(%)']}% | 净流入{row['主力净流入(亿)']}亿 | 涨停{row['涨停家数']}家\n"

    push_content += "\n> ⚠️ 数据基于集合竞价，开盘后可能变化，仅供参考！"
    return push_content


# ===================== 主函数 =====================
def main(top_n: int = CONFIG["top_n"]):
    # 1. 抓取行业+概念板块数据
    if HAS_RICH:
        console.print(f"[cyan]📡 正在抓取集合竞价后板块数据...[/cyan]")
    else:
        print("📡 正在抓取集合竞价后板块数据...")

    industry_df = fetch_board_data("industry")
    concept_df = fetch_board_data("concept")

    # 2. 抓取一字板股票数据
    if HAS_RICH:
        console.print(f"[cyan]📡 正在抓取竞价一字板股票数据...[/cyan]")
    else:
        print("📡 正在抓取竞价一字板股票数据...")

    limit_up_df = fetch_limit_up_stocks()

    # 3. 合并板块数据并计算评分
    all_board_df = pd.concat([industry_df, concept_df], ignore_index=True)
    hot_board_df = calculate_hot_board_score(all_board_df)

    # 4. 展示结果并生成推送内容
    board_content = display_hot_boards(hot_board_df, top_n)
    limit_up_content = display_limit_up_stocks(limit_up_df)

    # 5. 合并推送内容并发送微信消息
    total_content = board_content + "\n\n" + limit_up_content
    if total_content.strip():
        send_wechat_notification(
            title=f"【{datetime.now().strftime('%Y-%m-%d')}】早盘热门板块+一字板股票",
            content=total_content
        )


# ===================== 运行入口 =====================
if __name__ == "__main__":
    # 解析命令行参数（支持自定义显示前N个板块）
    parser = argparse.ArgumentParser(description="早盘集合竞价热门板块+一字板股票检测器")
    parser.add_argument("--topn", type=int, default=CONFIG["top_n"], help=f"显示前N个热门板块（默认{CONFIG['top_n']}）")
    args = parser.parse_args()

    # 检查运行时间（提示非交易时间）
    now = datetime.now()
    if now.weekday() >= 5:
        if HAS_RICH:
            console.print("[yellow]⚠️  当前为周末，非A股交易日，数据可能无效！[/yellow]")
        else:
            print("⚠️  当前为周末，非A股交易日，数据可能无效！")
    elif not (9 <= now.hour <= 15):
        if HAS_RICH:
            console.print("[yellow]⚠️  当前非A股交易时间（9:00-15:00），建议9:25后运行！[/yellow]")
        else:
            print("⚠️  当前非A股交易时间（9:00-15:00），建议9:25后运行！")

    # 执行主逻辑
    main(top_n=args.topn)