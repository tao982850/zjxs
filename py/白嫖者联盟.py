def categoryContent(self, tid, pg, filter=False, extend=None):
    pg = int(pg or 1)
    extend = extend or {}
    result = {"list": [], "page": pg, "pagecount": 0, "limit": 20, "total": 0}

    try:
        # 尝试多种分类ID（如果映射无效，直接透传）
        real_tid = self.CLASS_ID_MAP.get(tid, tid)
        params = {
            "kind": real_tid,
            "page": str(pg)
        }
        # 添加过滤参数（同原代码）
        for k in ["genre", "area", "year", "sort"]:
            if extend.get(k):
                val = str(extend[k])
                if k == "year" and val in ["2000-2009", "older"]:
                    continue  # 由本地过滤处理
                params[k] = val

        data = self._api_get("/browse/catalog", params)
        videos = []

        if data:
            # 尝试多种可能的列表字段
            cards = None
            if "cards" in data:
                cards = data["cards"]
            elif "list" in data:
                cards = data["list"]
            elif "data" in data and isinstance(data["data"], dict):
                cards = data["data"].get("cards") or data["data"].get("list")
            elif isinstance(data, list):  # 直接返回列表
                cards = data

            if cards:
                for card in cards:
                    item = self._parse_card(card)
                    if item:
                        # 本地年份过滤（同原代码）
                        year_val = str(extend.get("year", ""))
                        if year_val == "2000-2009":
                            try:
                                y = int(item["vod_year"])
                                if y < 2000 or y > 2009:
                                    continue
                            except:
                                continue
                        elif year_val == "older":
                            try:
                                y = int(item["vod_year"])
                                if y >= 2000:
                                    continue
                            except:
                                continue
                        videos.append(item)

            # 分页信息
            pagination = data.get("pagination") or data.get("page") or {}
            if pagination:
                result["pagecount"] = pagination.get("total_pages") or pagination.get("pagecount") or pg
                result["total"] = pagination.get("total", len(videos))
            else:
                # 若没有分页信息，根据是否有更多数据决定
                result["pagecount"] = pg if len(videos) > 0 else 0
                result["total"] = len(videos)

        result["list"] = videos
    except Exception as e:
        self._log(f"分类列表获取异常: {str(e)}")

    return result