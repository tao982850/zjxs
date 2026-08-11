import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "大师兄影视",
    siteUrl: "https://www.dsxys.me"
};

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

async function init(ext) {
    console.log("初始化爬虫:", appConfig.siteName);
}

// ===== 一级分类（站点导航 type_id） =====
const classList = [
    { type_id: "1", type_name: "电影" },
    { type_id: "2", type_name: "剧集" },
    { type_id: "3", type_name: "综艺" },
    { type_id: "4", type_name: "动漫" }
];

// ===== 二级类型筛选（站点 /k/ 路由实测，选中后替换 type 段为独立 tid） =====
// 站点片库筛选：area/class/lang 三者互斥，只能用一个；by 与 page 冲突，翻页时 by 留空
const subClassConfig = {
    "1": [
        ["全部", ""], ["动作片", "6"], ["喜剧片", "7"], ["爱情片", "8"],
        ["科幻片", "9"], ["奇幻片", "10"], ["恐怖片", "11"], ["剧情片", "12"],
        ["战争片", "20"], ["悬疑片", "21"], ["惊悚片", "22"], ["犯罪片", "23"],
        ["冒险片", "24"], ["动画片", "26"], ["武侠片", "45"], ["古装片", "46"],
        ["同性片", "47"], ["歌舞片", "48"], ["纪录片", "49"], ["网络电影", "50"]
    ],
    "2": [
        ["全部", ""], ["国产剧", "13"], ["港台剧", "14"], ["日韩剧", "15"],
        ["欧美剧", "16"], ["海外剧", "27"], ["短剧", "51"]
    ],
    "3": [["全部", ""], ["大陆综艺", "28"], ["港台综艺", "29"], ["日韩综艺", "30"], ["欧美综艺", "31"]],
    "4": [["全部", ""], ["国产动漫", "32"], ["日本动漫", "33"], ["欧美动漫", "34"], ["海外动漫", "35"]]
};

// ===== 通用筛选（area/class/lang 三者互斥，这里只暴露 area 和 year，by 留空避免与 page 冲突） =====
const AREA_FILTER = [["全部", ""], ["大陆", "大陆"], ["香港", "香港"], ["台湾", "台湾"],
    ["日本", "日本"], ["韩国", "韩国"], ["欧美", "欧美"], ["英国", "英国"],
    ["泰国", "泰国"], ["其它", "其它"]];
const YEAR_FILTER = [["全部", ""], ["2026", "2026"], ["2025", "2025"], ["2024", "2024"],
    ["2023", "2023"], ["2022", "2022"], ["2021", "2021"], ["2020", "2020"],
    ["2019", "2019"], ["2018", "2018"], ["2017", "2017"], ["2016", "2016"], ["2015", "2015"]];

function toFilterObj(arr) { return arr.map(g => ({ "n": g[0], "v": g[1] })); }

function buildFilters(tid) {
    const subs = subClassConfig[tid] || [["全部", ""]];
    return [
        { "key": "class", "name": "类型", "value": toFilterObj(subs) },
        { "key": "area",  "name": "地区", "value": toFilterObj(AREA_FILTER) },
        { "key": "year",  "name": "年份", "value": toFilterObj(YEAR_FILTER) }
    ];
}
const myFilters = {};
classList.forEach(item => { myFilters[item.type_id] = buildFilters(item.type_id); });

// ===== 分类 URL 构建 =====
// 站点片库路由（12 段，11 个分隔符）：
// /k/{tid}-{area}-{by}-{class}-{lang}---{page}---{year}.html
// 实测段位：segs[0]=tid, segs[1]=area, segs[2]=by, segs[3]=class, segs[4]=lang,
//           segs[8]=page, segs[11]=year
// 限制：
//   1. area/class/lang 三者互斥（同时用返回空）
//   2. by 与 page 冲突（翻页时 by 留空）
//   3. 二级类型选中后替换 tid，但替换后再加 area 会冲突
// 策略：
//   - 选了二级类型(class) → 替换 tid，area/year 不叠加
//   - 未选 class → 用 area + year + page 组合（实测有效）
function buildCategoryUrl(tid, buildCategoryUrl(tid, pg, extend) {
    extend = extend || {};
    pg = pg || 1;
    let typeId = tid;
    let area = "";
    let year = "";
    if (extend.class) {
        // 二级类型优先，替换 tid，不叠加其他筛选
        typeId = extend.class;
    } else {
        // 无二级类型时，area/year 可与 page 共存
        if (extend.area) area = encodeURIComponent(extend.area);
        if (extend.year) year = extend.year;
    }
    // 12 段（11 个分隔符）：
    // [0]=tid, [1]=area, [2]=by(空), [3]=class(空), [4]=lang(空),
    // [5-7]=空, [8]=page, [9-10]=空, [11]=year
    const segs = [typeId, area, "", "", "", "", "", "", String(pg), "", "", year];
    return appConfig.siteUrl + '/k/' + segs.join('-') + '.html';
}

// ===== 通用请求 =====
// drpy 不同引擎对响应载体字段不一致，逐一尝试所有可能字段
function extractResp(resp) {
    if (resp === undefined || resp === null) return '';
    if (typeof resp === 'string') return resp;
    if (typeof resp === 'number') return String(resp);
    if (typeof resp === 'object') {
        const fields = ['content', 'body', 'text', 'data', 'responseText', 'response', 'json', 'html'];
        for (let i = 0; i < fields.length; i++) {
            let v;
            try { v = resp[fields[i]]; } catch (e) { continue; }
            if (v === undefined || v === null || v === '') continue;
            if (typeof v === 'string' && v.length > 0) return v;
            if (typeof v === 'number') return String(v);
            if (typeof v === 'object') {
                try {
                    const s = JSON.stringify(v);
                    if (s && s.length > 2 && s !== '{}') return s;
                } catch (e) {}
            }
        }
        try {
            const s = JSON.stringify(resp);
            if (s && s.length > 2 && s !== '{}') return s;
        } catch (e) {}
    }
    return '';
}

async function httpGet(url, referer) {
    const headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Referer": referer || (appConfig.siteUrl + '/')
    };
    for (let attempt = 0; attempt < 3; attempt++) {
        try {
            let resp = await req(url, { method: "GET", headers: headers });
            let content = extractResp(resp);
            if (content.length > 0) return content;
            if (typeof request !== 'undefined') {
                try {
                    resp = await request(url, { method: "GET", headers: headers });
                    content = extractResp(resp);
                    if (content.length > 0) return content;
                } catch (e2) {}
            }
            console.warn("httpGet 第" + attempt + "次返回空, URL:", url);
            await new Promise(r => setTimeout(r, 500));
        } catch (e) {
            console.error("请求失败[" + attempt + "]:", e.message, "URL:", url);
            await new Promise(r => setTimeout(r, 800));
        }
    }
    return '';
}

function normalizePic(src) {
    if (!src) return '';
    if (src.startsWith('//')) return 'https:' + src;
    if (src.startsWith('http')) return src;
    if (src.startsWith('/')) return appConfig.siteUrl + src;
    return src;
}

// ===== 解析列表页（首页/分类/搜索通用 mxone 主题卡片结构） =====
function parseListHtml(html) {
    const $ = cheerio.load(html);
    const list = [];
    const seen = {};

    $('a.module-poster-item').each(function () {
        const card = $(this);
        let href = card.attr('href') || '';
        if (!href || href.indexOf('/dsx/') === -1) return;
        const m = href.match(/\/dsx\/(\d+)\.html/);
        if (!m) return;
        const vod_id = m[1];
        if (seen[vod_id]) return;

        let vod_name = (card.attr('title') || '').trim();
        if (!vod_name) {
            const img = card.find('img').first();
            vod_name = (img.attr('alt') || '').trim();
        }
        if (!vod_name) return;

        let vod_pic = card.find('.module-item-pic img').attr('data-original') || '';
        if (!vod_pic) vod_pic = card.find('img').attr('data-original') || '';
        if (!vod_pic) vod_pic = card.find('img').attr('src') || '';
        vod_pic = normalizePic(vod_pic);

        let vod_remarks = card.find('.module-item-note').first().text().trim();

        seen[vod_id] = true;
        list.push({ vod_id, vod_name, vod_pic, vod_remarks });
    });

    // 分页：从分页链接提取最大页码
    let maxPage = 0;
    $('a').each(function () {
        const href = $(this).attr('href') || '';
        // 分类片库分页 /k/{id}--------{page}---.html
        const m1 = href.match(/\/k\/\d+-*-(\d+)-*\.html/);
        if (m1) {
            const p = parseInt(m1[1]);
            if (!isNaN(p) && p > maxPage && p < 999) maxPage = p;
        }
        // 搜索分页 /s/xxx----------{page}---.html
        const m2 = href.match(/----------(\d+)---\.html/);
        if (m2) {
            const p = parseInt(m2[1]);
            if (!isNaN(p) && p > maxPage) maxPage = p;
        }
    });
    const pagecount = maxPage > 0 ? maxPage : (list.length > 0 ? 1 : 0);
    return { list, pagecount };
}

// ===== 首页：抓取首页推荐 =====
async function home(filter) {
    let list = [];
    try {
        const html = await httpGet(appConfig.siteUrl + '/');
        const $ = cheerio.load(html);
        const seen = {};
        $('a.module-poster-item').each(function () {
            const card = $(this);
            let href = card.attr('href') || '';
            const m = href.match(/\/dsx\/(\d+)\.html/);
            if (!m) return;
            const vod_id = m[1];
            if (seen[vod_id]) return;
            let vod_name = (card.attr('title') || '').trim();
            if (!vod_name) vod_name = (card.find('img').attr('alt') || '').trim();
            if (!vod_name) return;
            let vod_pic = card.find('.module-item-pic img').attr('data-original') || card.find('img').attr('data-original') || card.find('img').attr('src') || '';
            vod_pic = normalizePic(vod_pic);
            const vod_remarks = card.find('.module-item-note').first().text().trim();
            seen[vod_id] = true;
            list.push({ vod_id, vod_name, vod_pic, vod_remarks });
        });
        list = list.slice(0, 30);
    } catch (e) {
        console.error("首页获取失败:", e.message);
    }
    return JSON.stringify({ class: classList, filters: myFilters, list: list });
}

// ===== 分类：/k/{tid}-{area}------{page}---{year}.html =====
async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};
    try {
        const url = buildCategoryUrl(tid, pg, extend);
        const html = await httpGet(url);
        const result = parseListHtml(html);
        return JSON.stringify({ list: result.list, pagecount: result.pagecount });
    } catch (e) {
        console.error("分类列表获取失败:", e.message, e.stack);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

// ===== 搜索：/s/{wd}----------{pg}---.html =====
async function search(wd, quick, page) {
    page = page || 1;
    try {
        const kw = String(wd || '').trim();
        if (!kw) return JSON.stringify({ list: [], pagecount: 0 });
        const enc = encodeURIComponent(kw);
        const url = appConfig.siteUrl + '/s/' + enc + '----------' + page + '---.html';
        const html = await httpGet(url);
        const result = parseListHtml(html);
        return JSON.stringify({ list: result.list, pagecount: result.pagecount });
    } catch (e) {
        console.error("搜索失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

// ===== 详情：/dsx/{id}.html =====
async function detail(id) {
    try {
        const vid = String(id).replace(/[^0-9]/g, '');
        if (!vid) return JSON.stringify({ list: [] });
        const url = appConfig.siteUrl + '/dsx/' + vid + '.html';
        const html = await httpGet(url);
        const $ = cheerio.load(html);

        // 标题
        let vod_name = $('h1').first().text().trim();
        if (!vod_name) vod_name = $('.module-info-heading h1').first().text().trim();

        // 海报
        let vod_pic = $('.module-item-pic img').first().attr('data-original') || '';
        if (!vod_pic) vod_pic = $('.module-info-poster img').first().attr('data-original') || '';
        if (!vod_pic) vod_pic = $('meta[property="og:image"]').attr('content') || '';
        vod_pic = normalizePic(vod_pic);

        // 元数据：module-info-item（title 为 span 标签，content 为 div）
        let vod_director = '', vod_actor = '', vod_class = '', vod_area = '',
            vod_lang = '', vod_year = '', vod_remarks = '', vod_content = '';

        $('.module-info-item').each(function () {
            const item = $(this);
            const titleEl = item.find('.module-info-item-title').first();
            const key = titleEl.text().trim().replace(/[:：]/, '');
            if (!key) return;
            const contentEl = item.find('.module-info-item-content').first();
            const valA = [];
            contentEl.find('a').each(function () {
                const t = $(this).text().trim();
                if (t) valA.push(t);
            });
            const valText = contentEl.text().trim().replace(/^[:：]\s*/, '');
            const val = valA.length > 0 ? valA.join('/') : valText;

            if (key.indexOf('导演') !== -1) vod_director = val;
            else if (key.indexOf('主演') !== -1 || key.indexOf('演员') !== -1) vod_actor = val;
            else if (key.indexOf('类型') !== -1) vod_class = val;
            else if (key.indexOf('地区') !== -1 || key.indexOf('国家') !== -1) vod_area = val.replace(/[\[\]【】]/g, '');
            else if (key.indexOf('语言') !== -1) vod_lang = val;
            else if (key.indexOf('上映') !== -1 || key.indexOf('首映') !== -1 || key.indexOf('年份') !== -1) {
                const ym = val.match(/(\d{4})/);
                if (ym) vod_year = ym[1];
            }
            else if (key.indexOf('更新') !== -1 || key.indexOf('状态') !== -1) vod_remarks = val;
        });

        if (!vod_content) {
            vod_content = $('.module-info-introduction-content').first().text().trim()
                || $('.module-info-content').first().text().trim();
        }
        if (vod_content) vod_content = vod_content.substring(0, 500);

        // ===== 播放线路 =====
        // mxone 主题：.module-tab-item（线路标签，含 data-dropdown-value 属性）
        // 对应同顺序的 .module-play-list（剧集列表）
        // 注意：tab-item 内 <span> 是线路名，<small> 是集数数字，不能用 text() 整体取（会拼成"自营1线15"）
        const lines = [];
        const playlists = [];
        const sourceNames = [];
        $('.module-player-list .module-tab-item, .module-tab-items .module-tab-item').each(function () {
            const el = $(this);
            // 1. 优先取 data-dropdown-value 属性（纯净线路名）
            let name = el.attr('data-dropdown-value');
            // 2. 兜底：取 span 文本（避开 small 标签里的集数数字）
            if (!name) {
                const span = el.find('span').first();
                name = span.length ? span.text().trim() : '';
            }
            // 3. 再兜底：取整体文本并剔除尾部数字
            if (!name) {
                name = el.text().trim().replace(/\d+$/, '').trim();
            }
            if (name && name !== '选择播放源') sourceNames.push(name);
        });

        $('.module-play-list').each(function (idx) {
            const epList = [];
            $(this).find('a').each(function () {
                const ep = $(this);
                let epName = ep.text().trim();
                let epUrl = ep.attr('href') || '';
                if (!epUrl || (epUrl.indexOf('/video/') === -1 && epUrl.indexOf('/play/') === -1 && epUrl.indexOf('/v/') === -1)) return;
                if (!epUrl.startsWith('http')) epUrl = appConfig.siteUrl + epUrl.replace(/^\/+/, '');
                // 去掉"立即播放"字眼
                if (epName === '立即播放' || epName.indexOf('立即播放') !== -1) return;
                if (epName && epUrl) epList.push(epName + '$' + epUrl);
            });
            if (epList.length > 0) {
                lines.push(sourceNames[idx] || ('线路' + (idx + 1)));
                playlists.push(epList);
            }
        });

        if (lines.length === 0) {
            // 兜底：直接取所有播放链接
            const epList = [];
            $('a[href*="/video/"], a[href*="/play/"], a[href*="/v/"]').each(function () {
                const ep = $(this);
                const epName = ep.text().trim();
                let epUrl = ep.attr('href') || '';
                if (!epUrl || epName.indexOf('立即播放') !== -1) return;
                if (!epUrl.startsWith('http')) epUrl = appConfig.siteUrl + epUrl.replace(/^\/+/, '');
                if (epName && epUrl) epList.push(epName + '$' + epUrl);
            });
            if (epList.length > 0) {
                lines.push('默认线路');
                playlists.push(epList);
            }
        }

        // 追加官方线路：复用第一条线路的集数（播放页 URL），play 时直接调用解析器解析播放页
        // 用途：当直链线路播放失败时，可切换到官方线路让解析器自行解析播放页
        // 官方线路：爱奇艺/腾讯/芒果/哔哩/优酷，每个平台用对应解析器嗅探播放页
        if (playlists.length > 0) {
            ['爱奇艺', '腾讯', '芒果', '哔哩', '优酷'].forEach(function (name) {
                lines.push(name);
                playlists.push(playlists[0]);
            });
        }

        return JSON.stringify({
            list: [{
                vod_id: vid, vod_name, vod_pic, vod_actor, vod_director,
                vod_remarks, vod_year, vod_area, vod_lang, vod_content, vod_class,
                vod_play_from: lines.join('$$$'),
                vod_play_url: playlists.map(p => p.join('#')).join('$$$')
            }]
        });
    } catch (error) {
        console.error("解析详情异常:", error);
        return JSON.stringify({ list: [] });
    }
}

// ===== 提取 player_aaaa 完整 JSON 对象（括号平衡法，不依赖 </script> 紧跟） =====
// 播放页 player_aaaa 含嵌套对象 vod_data:{...}，非贪婪正则会在第一个 } 截断，
// 这里手动按括号深度匹配完整 JSON，同时处理字符串内的括号转义。
function extractPlayerAaaa(html) {
    const key = 'player_aaaa';
    const startIdx = html.indexOf(key);
    if (startIdx === -1) return null;
    let i = html.indexOf('{', startIdx);
    if (i === -1) return null;
    let depth = 0, inStr = false, escape = false, quote = '';
    const start = i;
    for (; i < html.length; i++) {
        const c = html[i];
        if (inStr) {
            if (escape) { escape = false; continue; }
            if (c === '\\') { escape = true; continue; }
            if (c === quote) { inStr = false; }
            continue;
        }
        if (c === '"' || c === "'") { inStr = true; quote = c; continue; }
        if (c === '{') depth++;
        else if (c === '}') {
            depth--;
            if (depth === 0) {
                const jsonStr = html.substring(start, i + 1);
                try { return JSON.parse(jsonStr); } catch (e) {
                    try { return JSON.parse(jsonStr.replace(/'/g, '"')); } catch (e2) { return null; }
                }
            }
        }
    }
    return null;
}

// ===== 播放（智能判断：官方外链嗅探 / 直链直接播放）=====
// 请求播放页提取 player_aaaa.url，根据 URL 特征自动选择播放方式：
// - 官方平台域名（iqiyi/qq/youku/mgtv/bilibili）-> parse:1 让播放器嗅探
// - m3u8/mp4 直链 -> parse:0 直接播放
async function play(flag, id, flags) {
    try {
        let playUrl = String(id || '');
        if (!playUrl.startsWith('http')) {
            playUrl = appConfig.siteUrl + '/' + playUrl.replace(/^\/+/, '');
        }

        // 请求播放页，提取真实视频地址
        const html = await httpGet(playUrl);
        const playerData = extractPlayerAaaa(html);
        
        let videoUrl = '';
        let videoFrom = '';
        
        if (playerData) {
            if (playerData.url) videoUrl = playerData.url;
            if (playerData.from) videoFrom = playerData.from;
        }
        
        // 如果没提取到，用播放页URL兜底
        if (!videoUrl) videoUrl = playUrl;

        // 判断是否为官方平台外链
        const officialDomains = ['iqiyi.com', 'iq.com', 'qq.com', 'v.qq.com', 
                                 'youku.com', 'mgtv.com', 'bilibili.com', 'b23.tv'];
        const isOfficial = officialDomains.some(d => videoUrl.indexOf(d) !== -1);
        
        // 判断是否为直链（m3u8/mp4）
        const isDirectLink = videoUrl.match(/\.(m3u8|mp4|flv)($|\?)/i) !== null;

        if (isOfficial) {
            // 官方平台外链：parse:1 让播放器嗅探解析
            return JSON.stringify({
                parse: 1,
                playUrl: "",
                url: videoUrl,
                header: { "User-Agent": UA, "Referer": appConfig.siteUrl + "/" },
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + "/" }
            });
        } else if (isDirectLink) {
            // m3u8/mp4 直链：parse:0 直接播放
            const referer = videoFrom ? (videoFrom.startsWith('http') ? videoFrom : appConfig.siteUrl) : appConfig.siteUrl;
            return JSON.stringify({
                parse: 0,
                playUrl: "",
                url: videoUrl,
                header: { "User-Agent": UA, "Referer": referer + "/" },
                Header: { "User-Agent": UA, "Referer": referer + "/" }
            });
        } else {
            // 其他未知类型：parse:1 兜底嗅探
            return JSON.stringify({
                parse: 1,
                playUrl: "",
                url: videoUrl,
                header: { "User-Agent": UA, "Referer": appConfig.siteUrl + "/" },
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + "/" }
            });
        }
    } catch (e) {
        console.error("播放失败:", e);
        return JSON.stringify({ parse: 0, url: "" });
    }
}

export default { init, home, category, detail, search, play };
