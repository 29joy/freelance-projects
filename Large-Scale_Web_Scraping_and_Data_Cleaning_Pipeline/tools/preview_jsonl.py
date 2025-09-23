# -*- coding: utf-8 -*-
"""
preview_jsonl.py  ——  所有站点通用预览器（批量/目录自动命名版）

新用法示例：
  # 1) 传入目录：为目录下每个 *.jsonl 生成一个 HTML
  python tools/preview_jsonl.py --inputs "deliveries/all_sites"

  # 2) 传入通配符：为每个匹配到的文件各生成一个 HTML
  python tools/preview_jsonl.py --inputs "deliveries/all_sites/*clean.jsonl"

  # 3) 可选：指定 --out 为某个目录，则所有预览写入该目录
  python tools/preview_jsonl.py --inputs "deliveries/all_sites/*clean.jsonl" --out "deliveries_pre_check/all_sites"

旧用法（单文件聚合到一个 HTML）也仍可用：提供 --out 且 --inputs 只指向单个文件时，会生成单一 HTML。
"""

import argparse
import glob
import json
import os
import sys
from html import escape as html_escape


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip("\n")
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as e:
                yield {
                    "__error__": f"{os.path.basename(path)}:{ln} JSON decode error: {e}",
                    "__raw__": line,
                }


def collect_records_from_file(file_path):
    records = []
    for obj in read_jsonl(file_path):
        records.append(obj)
    return records


def expand_input_paths(inputs):
    """将 --inputs 中的每个参数展开为文件列表：
    - 若是目录：抓取该目录下所有 *.jsonl（不递归）
    - 若是文件/通配符：glob 展开
    """
    files = []
    for token in inputs:
        if os.path.isdir(token):
            files.extend(glob.glob(os.path.join(token, "*.jsonl")))
        else:
            files.extend(glob.glob(token))
    files = sorted(set(files))
    if not files:
        print("No input files matched.", file=sys.stderr)
    return files


# —— 富渲染工具 —— #

IMG_LINE_PREFIX = "[Image:"
IMG_LINE_RECOG_PREFIX = "[Image: "


def render_content_block(text):
    """
    将 meta.data_info.content 渲染为 HTML：
      - 行级识别 [Image: https://…]  => <img>
      - 识别以 '## ' 开头的行 => <h3>
      - 其它行：按段落 <p> 输出；连续空行合并为一个段落分隔
      - ✅ 保留段落内原始换行：使用 <br> 连接
    """
    if text is None:
        return "<div class='content-empty'>（无内容）</div>"

    lines = text.splitlines()

    html_lines = []
    paragraph_buf = []

    def flush_paragraph():
        # ✅ 保留段内换行：对每行先转义，再用 <br> 连接
        if paragraph_buf:
            if any(seg.strip() for seg in paragraph_buf):
                safe_lines = [html_escape(seg) for seg in paragraph_buf]
                joined = "<br>".join(safe_lines)
                html_lines.append(f"<p>{joined}</p>")
            paragraph_buf.clear()

    for raw in lines:
        s = raw.strip()

        # 1) 图片行
        if s.startswith(IMG_LINE_PREFIX):
            flush_paragraph()
            inner = s[1:-1] if (s.endswith("]") and s.startswith("[")) else s
            if ":" in inner:
                url_part = inner.split(":", 1)[1].strip()
                url_part = url_part.strip(" ]")
            else:
                url_part = s
            url = url_part
            if url.lower().startswith(("http://", "https://")):
                html_lines.append(
                    "<div class='img-line'>"
                    f"<div class='img-box'><img src='{html_escape(url)}' alt='image' loading='lazy'></div>"
                    f"<div class='img-url'>{html_escape(url)}</div>"
                    "</div>"
                )
            else:
                paragraph_buf.append(s)
            continue

        # 2) 预览友好的二级标题
        if s.startswith("## "):
            flush_paragraph()
            title_text = s[3:].strip()
            html_lines.append(f"<h3>{html_escape(title_text)}</h3>")
            continue

        # 3) 普通行
        if s == "":
            flush_paragraph()
        else:
            # 保留原始行（不转义，留到 flush 时统一处理并加 <br>）
            paragraph_buf.append(raw)

    flush_paragraph()

    if not html_lines:
        return "<div class='content-empty'>（无渲染内容）</div>"

    return "\n".join(html_lines)


def render_title(title):
    if not title:
        return "<h2 class='title missing'>（无标题）</h2>"
    return f"<h2 class='title'>{html_escape(title)}</h2>"


def pretty_json(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return html_escape(str(obj))


def build_card(idx, rec):
    if "__error__" in rec:
        return f"""
        <div class="card error">
          <div class="card-head">
            <div class="card-index">#{idx}</div>
            <div class="id">解析错误</div>
          </div>
          <div class="error-msg"><pre>{html_escape(rec.get('__error__',''))}</pre></div>
          <details class="raw"><summary>RAW</summary><pre>{html_escape(rec.get('__raw__',''))}</pre></details>
        </div>
        """

    rid = rec.get("id", "")
    meta = rec.get("meta", {})
    # text 只提示，不展示全文
    others = {k: v for k, v in rec.items() if k not in ("id", "meta", "text")}

    data_info = meta.get("data_info", {}) if isinstance(meta, dict) else {}
    title = (data_info or {}).get("title")
    content = (data_info or {}).get("content")

    rendered_title = render_title(title)
    rendered_content = render_content_block(content)

    head_html = f"""
      <div class="card-head">
        <div class="card-index">#{idx}</div>
        <div class="id"><span class="label">id</span><code>{html_escape(str(rid))}</code></div>
      </div>
      <details class="meta" open>
        <summary>meta</summary>
        <pre class="json">{html_escape(pretty_json(meta))}</pre>
      </details>
    """

    text_html = f"""
      <details class="text" open>
        <summary>text</summary>
        <div class="text-note">见下方渲染</div>
      </details>
    """

    others_html = ""
    if others:
        others_html += "<details class='others' open><summary>其它顶层键</summary>"
        for k, v in others.items():
            others_html += (
                f"<div class='kv'>"
                f"<div class='k'>{html_escape(str(k))}</div>"
                f"<pre class='v'>{html_escape(pretty_json(v))}</pre>"
                f"</div>"
            )
        others_html += "</details>"

    body_html = f"""
      <div class="render-area">
        {rendered_title}
        {rendered_content}
      </div>
    """

    return f"""
    <div class="card">
      {head_html}
      {text_html}
      {others_html}
      {body_html}
    </div>
    """


def build_html(files, records):
    cards = [build_card(i, rec) for i, rec in enumerate(records, 1)]
    total = len(records)
    srcs = "<br>".join(html_escape(p) for p in files) if files else "(no inputs)"
    cards_html = "\n".join(cards)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>JSONL 预览</title>
  <style>
    :root {{
      --bg: #0b1020;
      --card: #121a2e;
      --muted: #7d8fb3;
      --text: #e7eefc;
      --accent: #4aa8ff;
      --ok: #22c55e;
      --warn: #f59e0b;
      --err: #ef4444;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--text); font: 14px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial; }}
    a {{ color: var(--accent); text-decoration: none; }}
    .container {{ max-width: 1100px; margin: 24px auto; padding: 0 16px; }}
    .header {{ margin-bottom: 16px; color: var(--muted); }}
    .files {{ font-family: var(--mono); color: var(--muted); font-size: 12px; }}
    .card {{
      background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
      backdrop-filter: blur(6px);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 14px;
      padding: 14px 16px;
      margin: 14px 0 20px;
      box-shadow: 0 6px 18px rgba(0,0,0,0.25);
    }}
    .card.error {{ border-color: var(--err); }}
    .card-head {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }}
    .card-index {{ font-family: var(--mono); color: var(--muted); font-size: 12px; padding: 2px 6px; border: 1px dashed rgba(255,255,255,0.15); border-radius: 6px; }}
    .id .label {{ display: inline-block; font-size: 12px; color: var(--muted); margin-right: 6px; }}
    .id code {{ font-family: var(--mono); background: rgba(255,255,255,0.05); padding: 2px 6px; border-radius: 6px; }}
    details {{ margin: 6px 0; }}
    summary {{ cursor: pointer; color: var(--muted); }}
    pre.json, pre.v, .error-msg pre, .raw pre {{
      background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.08);
      border-radius: 10px; padding: 10px; overflow: auto; white-space: pre-wrap; word-break: break-word;
      font-family: var(--mono);
    }}
    .text-note {{ color: var(--muted); font-style: italic; }}
    .kv {{ display: grid; grid-template-columns: 150px 1fr; gap: 8px; align-items: start; margin: 6px 0; }}
    .kv .k {{ color: var(--muted); font-family: var(--mono); }}
    .render-area {{ margin-top: 10px; padding-top: 10px; border-top: 1px dashed rgba(255,255,255,0.12); }}
    h2.title {{ margin: 0 0 8px; font-weight: 700; letter-spacing: .3px; }}
    h2.title.missing {{ color: var(--warn); }}
    h3 {{ margin: 12px 0 8px; font-weight: 700; }}
    p {{ margin: 8px 0; }}
    .img-line {{ margin: 8px 0 14px; }}
    .img-box {{
      width: 100%;
      max-height: 440px;
      overflow: hidden;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 12px;
      display: flex; align-items: center; justify-content: center;
    }}
    .img-box img {{ max-width: 100%; height: auto; display: block; }}
    .img-url {{ font-size: 12px; color: var(--muted); margin-top: 6px; word-break: break-all; }}
    .footer-note {{ margin: 30px 0 10px; color: var(--muted); font-size: 12px; text-align: center; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div><strong>预览文件</strong>（共 {total} 条）</div>
      <div class="files">{srcs}</div>
    </div>
    {cards_html}
    <div class="footer-note">预览仅用于结构/渲染校验；不做任何外站资源预拉取。</div>
  </div>
</body>
</html>
"""


def auto_out_path_for_file(file_path, base_out_dir=None):
    """
    依据输入文件，生成输出 HTML 路径：
      默认：deliveries_pre_check/<父目录名>/preview_<domain>.html
      若提供 base_out_dir（且是目录），则使用该目录替代 deliveries_pre_check/<父目录名>
    """
    parent_dir_name = os.path.basename(os.path.dirname(file_path)) or "preview"
    fname = os.path.basename(file_path)
    # 去掉常见后缀
    base = fname
    if base.endswith(".clean.jsonl"):
        base = base[: -len(".clean.jsonl")]
    elif base.endswith(".jsonl"):
        base = base[: -len(".jsonl")]
    domain = base  # 文件名前缀作为“站点域名/代号”

    if base_out_dir:
        out_dir = base_out_dir
    else:
        out_dir = os.path.join("deliveries_pre_check", parent_dir_name)

    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"preview_{domain}.html")


def main():
    ap = argparse.ArgumentParser(description="通用 JSONL 预览器（批量/目录自动命名版）")
    ap.add_argument(
        "--inputs", nargs="+", required=True, help="一个或多个 文件/目录/通配符 路径"
    )
    # --out 现在可选：若不提供，则为每个输入文件自动命名；若提供且是目录，则所有文件输出到该目录
    ap.add_argument("--out", required=False, help="可选：输出目录或单文件路径")
    args = ap.parse_args()

    files = expand_input_paths(args.inputs)
    if not files:
        sys.exit(1)

    # 情况 A：用户给了 --out，且只有一个输入文件且 --out 不是目录 => 旧行为：聚合输出到一个 HTML
    if (
        args.out
        and len(files) == 1
        and not os.path.isdir(args.out)
        and not args.out.endswith(os.sep)
    ):
        records = collect_records_from_file(files[0])
        html = build_html([files[0]], records)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Preview written to: {args.out}")
        return

    # 情况 B：批量模式（推荐）
    # 若 --out 是目录，则写入该目录；否则使用默认 deliveries_pre_check/<父目录名>。
    base_out_dir = None
    if args.out:
        # 若给的是目录（存在或以分隔符结尾），统一当作目录使用
        if os.path.isdir(args.out) or args.out.endswith(os.sep):
            base_out_dir = args.out
            os.makedirs(base_out_dir, exist_ok=True)
        else:
            # 给了一个非目录路径，但有多个文件 => 不合理；退化为把这个路径当目录创建
            base_out_dir = args.out
            os.makedirs(base_out_dir, exist_ok=True)

    wrote = 0
    for fp in files:
        recs = collect_records_from_file(fp)
        html = build_html([fp], recs)
        out_path = auto_out_path_for_file(fp, base_out_dir=base_out_dir)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Preview written to: {out_path}")
        wrote += 1

    if wrote == 0:
        print("No previews were written.", file=sys.stderr)


if __name__ == "__main__":
    main()
