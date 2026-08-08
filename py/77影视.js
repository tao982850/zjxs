// 刁民制作，仅供测试，测试完毕请24小时删除！
// ================================================================
// 77大片网 爬虫 - TVBox/影视仓 drpy2 ES模块格式
// 支持: 分类浏览 | 搜索 | 多播放源 | 加密URL解密
// ================================================================
import cheerio from 'assets://js/lib/cheerio.min.js';

// ===== 站点配置 =====
const appConfig = {
    siteName: "77大片网",
    siteUrl: "https://www.77dpw.vip"
};
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

// 备用域名列表 (网站换域名时自动尝试)
const fallbackDomains = [
    "https://www.77dpw.vip",
    "https://www.66dpw.vip",
    "https://77dpw.vip",
    "https://66dpw.vip"
];

// ===== 播放模式说明 =====
// 本爬虫直接使用网站原始播放源,不经过任何第三方解析接口
// 解密 player_aaaa.url 后分两种情况:
//   1. m3u8/mp4 直链 → parse:0, TVBox 直接播放
//   2. 网页URL(如芒果TV) → parse:1, TVBox 内置嗅探自动抓取页面视频流
// parse:1 是 TVBox 自带的网页嗅探功能,不是第三方解析

// ===== 分类列表 =====
const classList = [
    { type_id: "1", type_name: "电影" },
    { type_id: "2", type_name: "动漫" },
    { type_id: "3", type_name: "剧集" },
    { type_id: "4", type_name: "短剧" },
    { type_id: "5", type_name: "综艺" }
];

// ===== 筛选器 (通过 vodtype query 参数实现,无需验证码) =====
function getTypeFilter(catId) {
    let typeMap = {
        "1": [
            { n: "全部", v: "" }, { n: "喜剧", v: "喜剧" }, { n: "爱情", v: "爱情" },
            { n: "动作", v: "动作" }, { n: "恐怖", v: "恐怖" }, { n: "科幻", v: "科幻" },
            { n: "剧情", v: "剧情" }, { n: "犯罪", v: "犯罪" }, { n: "奇幻", v: "奇幻" },
            { n: "战争", v: "战争" }, { n: "悬疑", v: "悬疑" }, { n: "动画", v: "动画" },
            { n: "纪录", v: "纪录" }, { n: "惊悚", v: "惊悚" }, { n: "冒险", v: "冒险" },
            { n: "武侠", v: "武侠" }, { n: "古装", v: "古装" }, { n: "历史", v: "历史" },
            { n: "其他", v: "其他" }
        ],
        "2": [
            { n: "全部", v: "" }, { n: "热血", v: "热血" }, { n: "科幻", v: "科幻" },
            { n: "魔幻", v: "魔幻" }, { n: "励志", v: "励志" }, { n: "冒险", v: "冒险" },
            { n: "搞笑", v: "搞笑" }, { n: "推理", v: "推理" }, { n: "恋爱", v: "恋爱" },
            { n: "治愈", v: "治愈" }, { n: "校园", v: "校园" }, { n: "机战", v: "机战" },
            { n: "运动", v: "运动" }, { n: "悬疑", v: "悬疑" }, { n: "竞技", v: "竞技" },
            { n: "动作", v: "动作" }, { n: "童话", v: "童话" }, { n: "其他", v: "其他" }
        ],
        "3": [
            { n: "全部", v: "" }, { n: "言情", v: "言情" }, { n: "剧情", v: "剧情" },
            { n: "伦理", v: "伦理" }, { n: "喜剧", v: "喜剧" }, { n: "悬疑", v: "悬疑" },
            { n: "都市", v: "都市" }, { n: "古装", v: "古装" }, { n: "军事", v: "军事" },
            { n: "警匪", v: "警匪" }, { n: "历史", v: "历史" }, { n: "励志", v: "励志" },
            { n: "谍战", v: "谍战" }, { n: "青春", v: "青春" }, { n: "家庭", v: "家庭" },
            { n: "武侠", v: "武侠" }, { n: "科幻", v: "科幻" }, { n: "其他", v: "其他" }
        ],
        "4": [
            { n: "全部", v: "" }, { n: "甜宠", v: "甜宠" }, { n: "虐恋", v: "虐恋" },
            { n: "逆袭", v: "逆袭" }, { n: "穿越", v: "穿越" }, { n: "重生", v: "重生" },
            { n: "复仇", v: "复仇" }, { n: "豪门", v: "豪门" }, { n: "复仇", v: "复仇" },
            { n: "其他", v: "其他" }
        ],
        "5": [
            { n: "全部", v: "" }, { n: "脱口秀", v: "脱口秀" }, { n: "真人秀", v: "真人秀" },
            { n: "搞笑", v: "搞笑" }, { n: "选秀", v: "选秀" }, { n: "访谈", v: "访谈" },
            { n: "情感", v: "情感" }, { n: "生活", v: "生活" }, { n: "音乐", v: "音乐" },
            { n: "美食", v: "美食" }, { n: "游戏", v: "游戏" }, { n: "其他", v: "其他" }
        ]
    };
    return { key: "class", name: "类型", value: typeMap[catId] || typeMap["1"] };
}

function getAreaFilter(catId) {
    let areaMap = {
        "1": [
            { n: "全部", v: "" }, { n: "大陆", v: "大陆" }, { n: "香港", v: "香港" },
            { n: "台湾", v: "台湾" }, { n: "美国", v: "美国" }, { n: "日本", v: "日本" },
            { n: "韩国", v: "韩国" }, { n: "英国", v: "英国" }, { n: "法国", v: "法国" },
            { n: "德国", v: "德国" }, { n: "泰国", v: "泰国" }, { n: "印度", v: "印度" },
            { n: "其他", v: "其他" }
        ],
        "2": [
            { n: "全部", v: "" }, { n: "大陆", v: "大陆" }, { n: "日本", v: "日本" },
            { n: "美国", v: "美国" }, { n: "韩国", v: "韩国" }, { n: "其他", v: "其他" }
        ],
        "3": [
            { n: "全部", v: "" }, { n: "大陆", v: "大陆" }, { n: "香港", v: "香港" },
            { n: "台湾", v: "台湾" }, { n: "日本", v: "日本" }, { n: "韩国", v: "韩国" },
            { n: "美国", v: "美国" }, { n: "英国", v: "英国" }, { n: "泰国", v: "泰国" },
            { n: "其他", v: "其他" }
        ],
        "4": [
            { n: "全部", v: "" }, { n: "大陆", v: "大陆" }, { n: "其他", v: "其他" }
        ],
        "5": [
            { n: "全部", v: "" }, { n: "大陆", v: "大陆" }, { n: "香港", v: "香港" },
            { n: "台湾", v: "台湾" }, { n: "日本", v: "日本" }, { n: "韩国", v: "韩国" },
            { n: "美国", v: "美国" }, { n: "其他", v: "其他" }
        ]
    };
    return { key: "area", name: "地区", value: areaMap[catId] || areaMap["1"] };
}

function getYearFilter() {
    let years = [{ n: "全部", v: "" }];
    let currentYear = new Date().getFullYear();
    for (let y = currentYear; y >= 2010; y--) {
        years.push({ n: String(y), v: String(y) });
    }
    return { key: "year", name: "年份", value: years };
}

function getSortFilter() {
    return {
        key: "by", name: "排序", value: [
            { n: "按最新", v: "time" },
            { n: "按人气", v: "hits" },
            { n: "按评分", v: "score" }
        ]
    };
}

// 为每个分类生成筛选器
const myFilters = {};
classList.forEach(function (item) {
    myFilters[item.type_id] = [
        getTypeFilter(item.type_id),
        getAreaFilter(item.type_id),
        getYearFilter(),
        getSortFilter()
    ];
});

// ===== 工具函数 =====
function fixUrl(u) {
    if (!u) return '';
    if (u.startsWith('http')) return u;
    if (u.startsWith('//')) return 'https:' + u;
    if (u.startsWith('/')) return appConfig.siteUrl + u;
    return u;
}

// URL 编码 (兼容引擎不支持 encodeURIComponent 的情况)
function encodeQuery(s) {
    try {
        if (typeof encodeURIComponent === 'function') {
            return encodeURIComponent(s);
        }
    } catch (e) { }
    let result = '';
    for (let i = 0; i < s.length; i++) {
        let c = s.charCodeAt(i);
        if (c < 128) {
            result += s.charAt(i);
        } else if (c < 2048) {
            result += '%' + ((c >> 6) | 192).toString(16).toUpperCase();
            result += '%' + ((c & 63) | 128).toString(16).toUpperCase();
        } else {
            result += '%' + ((c >> 12) | 224).toString(16).toUpperCase();
            result += '%' + (((c >> 6) & 63) | 128).toString(16).toUpperCase();
            result += '%' + ((c & 63) | 128).toString(16).toUpperCase();
        }
    }
    return result;
}

// Base64 解码 (兼容环境)
function base64Decode(str) {
    try {
        if (typeof atob === 'function') {
            return atob(str);
        }
    } catch (e) { }
    // 手动 base64 解码
    let chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let output = "";
    str = str.replace(/[^A-Za-z0-9+/=]/g, "");
    for (let i = 0; i < str.length; i += 4) {
        let c1 = chars.indexOf(str.charAt(i));
        let c2 = chars.indexOf(str.charAt(i + 1));
        let c3 = chars.indexOf(str.charAt(i + 2));
        let c4 = chars.indexOf(str.charAt(i + 3));
        output += String.fromCharCode((c1 << 2) | (c2 >> 4));
        if (c3 !== -1 && str.charAt(i + 2) !== '=') {
            output += String.fromCharCode(((c2 & 15) << 4) | (c3 >> 2));
        }
        if (c4 !== -1 && str.charAt(i + 3) !== '=') {
            output += String.fromCharCode(((c3 & 3) << 6) | c4);
        }
    }
    return output;
}

// URL 解码 (兼容环境)
function urlDecode(str) {
    try {
        if (typeof decodeURIComponent === 'function') {
            return decodeURIComponent(str);
        }
    } catch (e) { }
    // 手动 URL 解码
    return str.replace(/%([0-9A-Fa-f]{2})/g, function (_, hex) {
        return String.fromCharCode(parseInt(hex, 16));
    });
}

// 解密播放地址 (maccms encrypt)
// encrypt=0: 明文, encrypt=1: URL编码, encrypt=2: base64(URL编码)
function decryptPlayUrl(url, encrypt) {
    if (!url) return '';
    try {
        if (encrypt === 2) {
            // base64 解码后再 URL 解码
            let decoded = base64Decode(url);
            return urlDecode(decoded);
        } else if (encrypt === 1) {
            return urlDecode(url);
        }
        return url;
    } catch (e) {
        console.error("解密播放地址失败: " + e.message);
        return url;
    }
}

// HTTP 请求封装
async function fetchUrl(url) {
    try {
        let resp = await req(url, {
            method: "GET",
            headers: {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": appConfig.siteUrl
            }
        });
        return resp.content || "";
    } catch (e) {
        console.error("请求失败: " + url + " - " + e.message);
        return "";
    }
}

// ===== 初始化 (动态域名抓取) =====
async function init(ext) {
    console.log("初始化爬虫: " + appConfig.siteName);

    // 遍历备用域名, 找到可用的
    for (let i = 0; i < fallbackDomains.length; i++) {
        try {
            let resp = await req(fallbackDomains[i] + "/", {
                method: "GET",
                headers: { "User-Agent": UA, "Accept": "text/html" }
            });
            let html = resp.content || "";
            if (html.length < 500) continue;

            // 从 maccms 配置中提取域名
            let macMatch = html.match(/var maccms\s*=\s*\{[^}]*"url":"([^"]+)"/);
            if (macMatch && macMatch[1]) {
                appConfig.siteUrl = fallbackDomains[i];
                console.log("域名可用: " + appConfig.siteUrl);
                return;
            }
            // 没找到 maccms, 但页面有效, 使用当前域名
            if (html.indexOf("vodtype") !== -1 || html.indexOf("voddetail") !== -1) {
                appConfig.siteUrl = fallbackDomains[i];
                console.log("使用备用域名: " + appConfig.siteUrl);
                return;
            }
        } catch (e) {
            console.error("域名 " + fallbackDomains[i] + " 尝试失败: " + e.message);
        }
    }
    console.error("所有备用域名均不可用, 使用默认: " + appConfig.siteUrl);
}

// ===== 解析列表页 HTML =====
function parseListHtml(html, filterYear) {
    let list = [];
    let pagecount = 1;
    let seen = {};

    try {
        let $ = cheerio.load(html);

        // 解析影片列表项
        $(".module-poster-item, .module-item").each(function () {
            let $a = $(this).is("a") ? $(this) : $(this).find("a").first();
            let href = $a.attr("href") || "";
            if (href.indexOf("voddetail") === -1) return;

            let vod_id = href;
            if (seen[vod_id]) return;

            let vod_name = $a.attr("title") || $(this).find(".module-poster-item-title, .module-item-title").text().trim() || "";
            let vod_pic = fixUrl(
                $(this).find("img").attr("data-original") ||
                $(this).find("img").attr("data-src") ||
                $(this).find("img").attr("src") || ""
            );
            let note = $(this).find(".module-item-note").text().trim() || "";

            // 构建封面备注: 年份 + 集数/描述
            let vod_remarks = note;

            // 优先使用筛选年份
            if (filterYear) {
                vod_remarks = filterYear + (note ? " | " + note : "");
            } else {
                // 从标题中提取年份 (如 "天眸之爱 (2018)")
                let yearMatch = vod_name.match(/\((\d{4})\)/) || vod_name.match(/(\d{4})/);
                if (yearMatch && yearMatch[1]) {
                    let extractedYear = yearMatch[1];
                    // 确保是合理的年份 (2010-当前年份)
                    let y = parseInt(extractedYear);
                    let curY = new Date().getFullYear();
                    if (y >= 2010 && y <= curY + 1) {
                        vod_remarks = extractedYear + (note ? " | " + note : "");
                    }
                }
            }

            if (vod_name && vod_id) {
                seen[vod_id] = true;
                list.push({ vod_id, vod_name, vod_pic, vod_remarks });
            }
        });

        // 解析分页: 支持 vodtype/ID-page.html 和 query ?page=N 两种格式
        $(".page-link, .num-page, a[href*='vodtype']").each(function () {
            let href = $(this).attr("href") || "";
            let m = href.match(/vodtype\/\d+-(\d+)\.html/) || href.match(/[?&]page=(\d+)/);
            if (m) {
                let p = parseInt(m[1]);
                if (p > pagecount) pagecount = p;
            }
        });

        // 如果没有找到分页信息, 检查是否有下一页
        let $next = $(".page-next, a:contains('下一页'), a:contains('Next')");
        if ($next.length > 0 && list.length > 0) {
            pagecount = 999;
        }
    } catch (e) {
        console.error("解析列表页失败: " + e.message);
    }

    return { list, pagecount };
}

// ===== 首页推荐 =====
async function home(filter) {
    let list = [];
    try {
        let html = await fetchUrl(appConfig.siteUrl + "/vodtype/1.html");
        let result = parseListHtml(html);
        list = result.list.slice(0, 30);
    } catch (e) {
        console.error("首页推荐获取失败: " + e.message);
    }

    return JSON.stringify({
        class: classList,
        filters: myFilters,
        list: list
    });
}

// ===== 分类列表 (支持筛选器) =====
async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};

    try {
        // 构建带筛选参数的URL (vodtype + query 参数)
        let params = [];
        if (extend.class) params.push("class=" + encodeQuery(extend.class));
        if (extend.area) params.push("area=" + encodeQuery(extend.area));
        if (extend.year) params.push("year=" + extend.year);
        if (extend.by) params.push("by=" + extend.by);
        params.push("page=" + pg);

        let url = appConfig.siteUrl + "/vodtype/" + tid + ".html?" + params.join("&");

        let html = await fetchUrl(url);
        let result = parseListHtml(html, extend.year || "");
        return JSON.stringify(result);
    } catch (e) {
        console.error("分类列表获取失败: " + e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

// ===== 搜索 (使用 suggest API 避免验证码) =====
async function search(wd, quick, page) {
    page = page || 1;
    try {
        let list = [];

        if (page === 1) {
            // 使用 suggest API 获取搜索结果
            let url = appConfig.siteUrl + "/index.php/ajax/suggest?mid=1&wd=" + encodeQuery(wd) + "&limit=30";
            let html = await fetchUrl(url);
            let data = JSON.parse(html);

            if (data && data.list && data.list.length > 0) {
                for (let i = 0; i < data.list.length; i++) {
                    let item = data.list[i];
                    list.push({
                        vod_id: "/voddetail/" + item.id + ".html",
                        vod_name: item.name || "",
                        vod_pic: fixUrl(item.pic || ""),
                        vod_remarks: ""
                    });
                }
            }
        }

        return JSON.stringify({ list: list, pagecount: 1 });
    } catch (e) {
        console.error("搜索失败: " + e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

// 剧集排序: 支持 "第X集" 和 "X" 两种格式
function sortEpisodes(arr) {
    return arr.sort(function (a, b) {
        let getNum = function (name) {
            let m = name.match(/第(\d+)[集话]/i);
            if (m) return parseInt(m[1]);
            m = name.match(/(\d+)/);
            return m ? parseInt(m[1]) : 0;
        };
        return getNum(a.name) - getNum(b.name);
    });
}

// ===== 详情页 =====
async function detail(id) {
    try {
        let html = await fetchUrl(appConfig.siteUrl + id);
        let $ = cheerio.load(html);

        // 标题
        let vod_name = $("h1").first().text().trim();

        // 封面图
        let vod_pic = "";
        let $pic = $(".module-info-poster .module-item-pic img, .module-item-cover .module-item-pic img").first();
        if ($pic.length > 0) {
            vod_pic = fixUrl($pic.attr("data-original") || $pic.attr("src") || "");
        }

        // 详情信息
        let vod_director = "";
        let vod_actor = "";
        let vod_area = "";
        let vod_year = "";
        let vod_content = "";
        let vod_class = "";
        let vod_remarks = "";

        // 解析信息项
        $(".module-info-item").each(function () {
            let title = $(this).find(".module-info-item-title").text().trim();
            let content = $(this).find(".module-info-item-content").text().trim();

            if (title.indexOf("导演") !== -1) {
                vod_director = $(this).find("a").map(function () { return $(this).text().trim(); }).get().join(",") || content;
            }
            if (title.indexOf("主演") !== -1) {
                vod_actor = $(this).find("a").map(function () { return $(this).text().trim(); }).get().join(",") || content;
            }
            if (title.indexOf("类型") !== -1) {
                vod_class = content;
            }
            if (title.indexOf("地区") !== -1) {
                vod_area = content;
            }
            if (title.indexOf("年份") !== -1 || title.indexOf("时间") !== -1) {
                vod_year = content;
            }
            if (title.indexOf("更新") !== -1) {
                vod_remarks = content;
            }
        });

        // 从标签链接中提取年份和地区
        if (!vod_year) {
            $(".module-info-tag-link a").each(function () {
                let text = $(this).text().trim();
                if (/^\d{4}$/.test(text) && !vod_year) {
                    vod_year = text;
                }
            });
        }
        if (!vod_area) {
            $(".module-info-tag-link a").each(function () {
                let text = $(this).text().trim();
                if ((text.indexOf("大陆") !== -1 || text.indexOf("美国") !== -1 || text.indexOf("日本") !== -1 ||
                    text.indexOf("韩国") !== -1 || text.indexOf("香港") !== -1 || text.indexOf("台湾") !== -1 ||
                    text.indexOf("英国") !== -1 || text.indexOf("法国") !== -1) && !vod_area) {
                    vod_area = text;
                }
            });
        }

        // 简介
        let $intro = $(".module-info-introduction-content p, .module-info-introduction-content, .video-info-content");
        if ($intro.length > 0) {
            vod_content = $intro.first().text().replace(/简介[：:]\s*/, "").trim();
        }

        // ===== 解析播放源和剧集 =====
        let lines = [];
        let playlists = [];

        // 获取播放源名称列表
        let sourceNames = [];
        $(".module-tab-item.tab-item").each(function () {
            let name = $(this).attr("data-dropdown-value") || $(this).find("span").text().trim();
            if (name) sourceNames.push(name);
        });

        // 获取每个播放源的剧集列表 (按 panel 顺序)
        let panelIndex = 0;
        $("[id^='panel']").each(function () {
            let episodes = [];
            let epArray = [];

            $(this).find(".module-play-list-link").each(function () {
                let name = $(this).find("span").text().trim() || $(this).text().trim();
                let href = $(this).attr("href") || "";
                if (name && href) {
                    epArray.push({ name: name, href: href });
                }
            });

            // 按集数排序
            sortEpisodes(epArray);

            epArray.forEach(function (ep) {
                episodes.push(ep.name + "$" + ep.href);
            });

            if (episodes.length > 0) {
                let lineName = sourceNames[panelIndex] || ("线路" + (panelIndex + 1));
                lines.push(lineName);
                playlists.push(episodes);
            }
            panelIndex++;
        });

        // 备用: 如果没有找到 panel, 全局搜索播放链接
        if (lines.length === 0) {
            let episodes = [];
            let epArray = [];
            let seenEp = {};

            $(".module-play-list-link").each(function () {
                let name = $(this).find("span").text().trim() || $(this).text().trim();
                let href = $(this).attr("href") || "";
                let key = name + "_" + href;
                if (name && href && !seenEp[key]) {
                    seenEp[key] = true;
                    epArray.push({ name: name, href: href });
                }
            });

            sortEpisodes(epArray);
            epArray.forEach(function (ep) {
                episodes.push(ep.name + "$" + ep.href);
            });

            if (episodes.length > 0) {
                lines.push("默认");
                playlists.push(episodes);
            }
        }

        if (lines.length === 0) {
            lines.push("默认");
            playlists.push(["暂无播放地址$" + id]);
        }

        // 构建播放数据
        let vod_play_from = lines.join("$$$");
        let vod_play_url = playlists.map(function (eps) { return eps.join("#"); }).join("$$$");

        return JSON.stringify({
            list: [{
                vod_id: id,
                vod_name: vod_name,
                vod_pic: vod_pic,
                vod_actor: vod_actor,
                vod_director: vod_director,
                vod_remarks: vod_remarks,
                vod_year: vod_year,
                vod_area: vod_area,
                vod_content: vod_content,
                vod_class: vod_class,
                vod_play_from: vod_play_from,
                vod_play_url: vod_play_url
            }]
        });
    } catch (e) {
        console.error("详情页解析失败: " + e.message);
        return JSON.stringify({ list: [] });
    }
}

// ===== 播放 (解密 player_aaaa) =====
async function play(flag, id, flags) {
    try {
        // 如果 id 已经是完整 URL, 直接返回
        if (id.startsWith("http")) {
            return JSON.stringify({
                parse: 0,
                header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: id
            });
        }

        // 请求播放页
        let html = await fetchUrl(appConfig.siteUrl + id);

        // 解析 player_aaaa JSON
        let playerMatch = html.match(/var\s+player_aaaa\s*=\s*(\{[\s\S]+?\})\s*<\/script>/);
        if (!playerMatch) {
            // 尝试更宽松的匹配
            playerMatch = html.match(/player_aaaa\s*=\s*(\{[^}]+\})/);
        }

        if (playerMatch) {
            try {
                let playerData = JSON.parse(playerMatch[1]);
                let encrypt = playerData.encrypt || 0;
                let playUrl = decryptPlayUrl(playerData.url, encrypt);

                if (playUrl) {
                    // 判断是否为直链 (m3u8/mp4/flv)
                    // 直链 → parse:0, TVBox 直接播放,无需任何解析
                    if (playUrl.indexOf(".m3u8") !== -1 || playUrl.indexOf(".mp4") !== -1 || playUrl.indexOf(".flv") !== -1) {
                        return JSON.stringify({
                            parse: 0,
                            header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                            url: playUrl
                        });
                    }

                    // 网页URL (如芒果TV/爱奇艺页面) → parse:1
                    // TVBox 内置浏览器嗅探: 打开网页,自动抓取页面中的视频流
                    // 这是 TVBox 自带功能,不经过第三方解析接口
                    return JSON.stringify({
                        parse: 1,
                        header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                        url: playUrl
                    });
                }
            } catch (e) {
                console.error("解析player_aaaa失败: " + e.message);
            }
        }

        // 尝试匹配 m3u8 URL
        let urlMatch = html.match(/"url"\s*[:=]\s*"([^"]+\.m3u8[^"]*)"/);
        if (urlMatch) {
            return JSON.stringify({
                parse: 0,
                header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: urlMatch[1].replace(/\\/g, '')
            });
        }

        // 尝试 iframe
        let $ = cheerio.load(html);
        let iframeSrc = $("iframe").attr("src");
        if (iframeSrc) {
            return JSON.stringify({
                parse: 1,
                header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
                url: fixUrl(iframeSrc)
            });
        }

        return JSON.stringify({
            parse: 1,
            header: { "User-Agent": UA, "Referer": appConfig.siteUrl },
            url: appConfig.siteUrl + id
        });
    } catch (e) {
        console.error("播放解析失败: " + e.message);
        return JSON.stringify({ parse: 0, url: "" });
    }
}

// ===== 导出模块 =====
export default {
    init,
    home,
    category,
    search,
    detail,
    play
};
