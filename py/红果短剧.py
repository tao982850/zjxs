def _item(x):
    x = x or {}
    vd = x.get("video_data") if isinstance(x.get("video_data"), dict) else x
    sid = str(
        vd.get("series_id")
        or vd.get("seriesId")
        or x.get("series_id")
        or x.get("seriesId")
        or x.get("keyword")
        or vd.get("keyword")
        or ""
    )
    name = str(
        vd.get("series_title")
        or vd.get("series_name")
        or x.get("series_name")
        or x.get("name")
        or "未命名"
    )
    count = vd.get("episode_cnt") or x.get("episode_cnt") or 0
    pic = str(vd.get("series_cover") or x.get("series_cover") or "")
    intro = str(vd.get("series_intro") or x.get("series_intro") or "")
    return {
        "vod_id": sid,
        "vod_name": name,
        "vod_pic": pic,
        "vod_remarks": ("全%s集" % count) if count else "",
        "vod_content": intro,
    }


def _cat_item(x):
    return _item(x)


def _filter_group(key, name, values):
    return {"key": key, "name": name, "value": [{"n": n, "v": v} for n, v in values]}


def _search_loader(key: str) -> dict:
    """拉取搜索页 loaderData，失败重试；兼容不同路由键命名。"""
    last = {}
    key_text = str(key or "").strip()
    if not key_text:
        return last

    # 站点可能用路径式 /search/xxx，也可能用查询式 /search?keyword=xxx
    urls = (
        SITE + "/search/" + quote(key_text, safe=""),
        SITE + "/search?" + urlencode({"keyword": key_text}),
    )

    for attempt in range(3):
        for url in urls:
            try:
                data = _data(url)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            loader = data.get("loaderData") or {}
            if not isinstance(loader, dict):
                continue

            page = {}

            # 1) 直接扫描：任何挂载了 searchList 的 loader 都认
            for value in loader.values():
                if isinstance(value, dict) and value.get("searchList"):
                    page = value
                    break

            # 2) 显式候选键（含历史版本）
            if not page:
                for name in (
                    "search_(keyword)/page",
                    "search_$keyword/page",
                    "search/page",
                    "search",
                ):
                    value = loader.get(name)
                    if isinstance(value, dict) and value.get("searchList"):
                        page = value
                        break

            if page.get("searchList"):
                return page
            if page and not last:
                last = page

        try:
            time.sleep(0.5 * (attempt + 1))
        except Exception:
            pass
    return last


def _search_by_keywords(keywords, page: int) -> dict:
    """多关键词轮换：第 N 页用第 N 个关键词（循环），避免搜索无法翻页。"""
    page = max(1, int(page or 1))
    kws = [k for k in (keywords or []) if k]
    if not kws:
        kws = ["短剧"]
    key = kws[(page - 1) % len(kws)]
    p = _search_loader(key)
    rows = p.get("searchList") or []
    # 去重空 id
    out = []
    seen = set()
    for x in rows:
        it = _item(x)
        vid = str(it.get("vod_id") or "")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        out.append(it)
    # 虚拟页数：关键词数；若站点有 totalCount 也参考
    total = int(p.get("totalCount") or 0)
    pagecount = max(len(kws), (total + 9) // 10 if total else len(kws))
    return {
        "page": page,
        "pagecount": max(1, pagecount),
        "limit": len(out),
        "total": total or len(out) * pagecount,
        "list": out,
    }