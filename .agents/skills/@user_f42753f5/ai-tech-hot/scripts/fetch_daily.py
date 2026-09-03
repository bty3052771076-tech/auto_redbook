#!/usr/bin/env python3
import sys
import re
import json

def parse_daily_markdown(text):
    items = []
    current_item = None
    date_match = re.search(r'AI 技术日报 - (\d{4}-\d{2}-\d{2})', text)
    date_str = date_match.group(1) if date_match else None

    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        num_match = re.match(r'^(\d+)\.\s*\*\*(.+?)\*\*', line)
        if num_match:
            if current_item:
                items.append(current_item)
            current_item = {
                'number': int(num_match.group(1)),
                'title': num_match.group(2),
                'summary': '',
                'url': ''
            }
        elif current_item:
            url_match = re.search(r'https?://[^\s\)]+', line)
            if url_match:
                current_item['url'] = url_match.group(0)
            elif line and not line.startswith('#') and not line.startswith('---'):
                if current_item['summary']:
                    current_item['summary'] += ' '
                current_item['summary'] += line
        i += 1

    if current_item:
        items.append(current_item)

    return {'date': date_str, 'items': items}

def format_output(data):
    lines = []
    date_str = data['date'] or '未知日期'
    lines.append(f'🔥 今日 AI 技术热点（{date_str}）')
    lines.append('')

    for item in data['items']:
        lines.append(f"{item['number']}. **{item['title']}**")
        if item['summary']:
            lines.append(f"   {item['summary']}")
        if item['url']:
            lines.append(f"   🔗 {item['url']}")
        lines.append('')

    lines.append('---')
    lines.append('📌 出处：www.theaiera.cn')
    lines.append('📢 公众号：AI人工智能时代')
    return '\n'.join(lines)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    data = parse_daily_markdown(text)
    print(format_output(data))
