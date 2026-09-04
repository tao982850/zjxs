import cheerio from 'assets://js/lib/cheerio.min.js';

// ============ 站点配置 ============
const appConfig = {
  siteName: "影视大全",
  siteUrl: "https://www.iysdq.tv"
};

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

async function init(ext) {
  console.log("初始化爬虫:", appConfig.siteName);
}

// ============ 分类与筛选 ============
const classList = [
  { type_id: "1", type_name: "电影" },
  { type_id: "2", type_name: "剧集" },
  { type_id: "3", type_name: "综艺" },
  { type_id: "4", type_name: "动漫" },
  { type_id: "5", type_name: "短剧" }
];

// 子分类（对应 vodshow 12段路由段4: class）
const SUB_CLASS = {
  "1": [["全部",""],["动作片","动作片"],["喜剧片","喜剧片"],["科幻片","科幻片"],["恐怖片","恐怖片"],["爱情片","爱情片"],["剧情片","剧情片"],["战争片","战争片"],["记录片","记录片"],["动画片","动画片"],["惊悚","惊悚"],["犯罪","犯罪"],["悬疑","悬疑"],["冒险","冒险"],["奇幻","奇幻"],["家庭","家庭"],["历史","历史"],["传记","传记"],["古装","古装"],["音乐","音乐"],["同性","同性"],["运动","运动"],["武侠","武侠"],["短片","短片"],["歌舞","歌舞"],["西部","西部"],["儿童","儿童"],["灾难","灾难"],["戏曲","戏曲"],["真人秀","真人秀"],["青春","青春"]],
  "2": [["全部",""],["国产剧","国产剧"],["欧美剧","欧美剧"],["香港剧","香港剧"],["韩国剧","韩国剧"],["台湾剧","台湾剧"],["日本剧","日本剧"],["海外剧","海外剧"],["泰国剧","泰国剧"]],
  "3": [["全部",""],["大陆综艺","大陆综艺"],["港台综艺","港台综艺"],["日韩综艺","日韩综艺"],["欧美综艺","欧美综艺"],["真人秀","真人秀"],["纪录片","纪录片"],["脱口秀","脱口秀"],["音乐","音乐"],["歌舞","歌舞"]],
  "4": [["全部",""],["国产动漫","国产动漫"],["日韩动漫","日韩动漫"],["欧美动漫","欧美动漫"],["港台动漫","港台动漫"],["海外动漫","海外动漫"]],
  "5": [["全部",""],["女频恋爱","女频恋爱"],["反转爽剧","反转爽剧"],["古装仙侠","古装仙侠"],["年代穿越","年代穿越"],["脑洞悬疑","脑洞悬疑"],["现代都市","现代都市"]]
};

const AREA_FILTER = [["全部",""],["大陆","大陆"],["香港","香港"],["台湾","台湾"],["美国","美国"],["日本","日本"],["韩国","韩国"],["英国","英国"],["法国","法国"],["德国","德国"],["意大利","意大利"],["西班牙","西班牙"],["俄罗斯","俄罗斯"],["加拿大","加拿大"],["印度","印度"],["泰国","泰国"],["其它","其它"]];

const LANG_FILTER = [["全部",""],["国语","国语"],["粤语","粤语"],["闽南语","闽南语"],["英语","英语"],["韩语","韩语"],["日语","日语"],["法语","法语"],["德语","德语"],["其它","其它"]];

const SORT_FILTER = [["最新","time"],["人气","hits"],["评分","score"]];

function toFilterObj(arr) {
  return arr.map(function(g) { return { "n": g[0], "v": g[1] }; });
}

function buildFilters(tid) {
  return [
    { "key": "sub", "name": "类型", "value": toFilterObj(SUB_CLASS[tid] || [["全部",""]]) },
    { "key": "area", "name": "地区", "value": toFilterObj(AREA_FILTER) },
    { "key": "by", "name": "排序", "value": toFilterObj(SORT_FILTER) },
    { "key": "lang", "name": "语言", "value": toFilterObj(LANG_FILTER) }
  ];
}

var myFilters = {};
classList.forEach(function(item) { myFilters[item.type_id] = buildFilters(item.type_id); });

// ============ URL 构造 ============
// vodshow 12段路由: /vodshow/{tid}-{area}-{by}-{class}-{lang}-{}-{}-{letter}-{}-{}-{}-{page}.html
// 段位: 1=tid 2=area 3=by 4=class 5=lang 6-7=空 8=letter 9-11=空 12=page
function buildCategoryUrl(tid, pg, extend) {
  extend = extend || {};
  pg = pg || 1;
  var segs = [
    String(tid),
    encodeURIComponent(extend.area || ""),
    extend.by || "",
    encodeURIComponent(extend.sub || extend.class || ""),
    encodeURIComponent(extend.lang || ""),
    "", "",
    extend.letter || "",
    "", "", "",
    String(pg)
  ];
  return appConfig.siteUrl + '/vodshow/' + segs.join('-') + '.html';
}

// 搜索 14段路由: /vodsearch/{wd}----------{page}---.html (段11=页码)
function buildSearchUrl(kw, page) {
  page = page || 1;
  if (page <= 1) {
    return appConfig.siteUrl + '/vodsearch/' + encodeURIComponent(kw) + '-------------.html';
  }
  return appConfig.siteUrl + '/vodsearch/' + encodeURIComponent(kw) + '----------' + page + '---.html';
}

// ============ 网络层 ============
async function httpGet(url, referer) {
  var headers = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "identity",
    "Referer": referer || (appConfig.siteUrl + '/')
  };
  for (var i = 0; i < 3; i++) {
    try {
      var resp = await req(url, { method: "GET", headers: headers });
      var content = resp.content || '';
      if (typeof content !== 'string') content = String(content);
      if (content.length > 200) return content;
      await new Promise(function(r) { setTimeout(r, 500); });
    } catch (e) {
      console.error("请求失败[" + i + "]:", e.message);
      await new Promise(function(r) { setTimeout(r, 800); });
    }
  }
  return '';
}

function normalizePic(src) {
  if (!src) return '';
  if (src.indexOf('//') === 0) return 'https:' + src;
  if (src.indexOf('http') === 0) return src;
  if (src.indexOf('/') === 0) return appConfig.siteUrl + src;
  return appConfig.siteUrl + '/' + src.replace(/^\.?\//, '');
}

// ============ 列表解析 ============
// 卡片选择器: a.public-list-exp (title + data-src 图片)
function parseVodList(html) {
  var $ = cheerio.load(html);
  var list = [];
  $('a.public-list-exp').each(function() {
    var card = $(this);
    var href = card.attr('href') || '';
    var m = href.match(/voddetail\/(\d+)/);
    if (!m) return;
    var name = (card.attr('title') || '').trim();
    if (!name) return;
    var img = card.find('img').first();
    var pic = img.attr('data-src') || img.attr('src') || '';
    pic = normalizePic(pic);
    var note = card.find('.public-list-prt, .public-prt, .remarks, .note').first().text().trim();
    if (!note) {
      var span = card.find('span').last();
      note = span.text().trim();
    }
    list.push({ vod_id: m[1], vod_name: name, vod_pic: pic, vod_remarks: note });
  });
  // 分页: 优先从 .rg10 提取总页数 (格式: "1 / 1713页")
  var pagecount = 0;
  $('.rg10, .page-small').each(function() {
    var t = $(this).text().replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
    var pm = t.match(/(\d+)\s*\/\s*(\d+)\s*页/);
    if (pm) {
      var tp = parseInt(pm[2], 10);
      if (tp > pagecount) pagecount = tp;
    }
  });
  // 备选: 从 hl-total JS 提取总数计算页数 (总数 / 每页数)
  if (pagecount === 0) {
    var tm = html.match(/\.hl-total'\)\.html\('(\d+)'\)/);
    if (tm) {
      var total = parseInt(tm[1], 10);
      if (total > 0 && list.length > 0) pagecount = Math.ceil(total / list.length);
    }
  }
  // 备选: 从分页链接提取最大页码
  if (pagecount === 0) {
    var maxPage = 0;
    $('a[href*="/vodshow/"], a[href*="/vodsearch/"], a[href*="/vodtype/"]').each(function() {
      var href = $(this).attr('href') || '';
      var mm = href.match(/\/(vodshow|vodsearch|vodtype)\/[^\/]+\.html/);
      if (!mm) return;
      var segs = mm[0].replace(/\/(vodshow|vodsearch|vodtype)\//, '').replace('.html', '').split('-');
      for (var si = 0; si < segs.length; si++) {
        var p = parseInt(segs[si], 10);
        if (!isNaN(p) && p > maxPage && p < 10000) maxPage = p;
      }
    });
    if (maxPage === 0) {
      $('.pages a, .page-link').each(function() {
        var t = $(this).text().trim();
        if (/^\d+$/.test(t)) {
          var p = parseInt(t, 10);
          if (p > maxPage && p < 10000) maxPage = p;
        }
      });
    }
    pagecount = maxPage;
  }
  if (pagecount === 0 && list.length > 0) pagecount = 1;
  return { list: list, pagecount: pagecount };
}

// 搜索结果同样用 public-list-exp
function parseSearchList(html) {
  return parseVodList(html);
}

// 合并 filter 与 extend
function mergeFilter(extend, filter) {
  var out = Object.assign({}, extend);
  if (filter) {
    if (Array.isArray(filter)) {
      filter.forEach(function(f) { if (f && typeof f === 'object') Object.assign(out, f); });
    } else if (typeof filter === 'object') {
      Object.assign(out, filter);
    }
  }
  return out;
}

// ============ 接口 ============
async function home(filter) {
  var list = [];
  try {
    var html = await httpGet(appConfig.siteUrl + '/');
    list = parseVodList(html).list.slice(0, 30);
  } catch (e) {
    console.error("首页失败:", e.message);
  }
  return JSON.stringify({ class: classList, filters: myFilters, list: list });
}

async function category(tid, pg, filter, extend) {
  pg = pg || 1;
  extend = extend || {};
  try {
    var merged = mergeFilter(extend, filter);
    var url = buildCategoryUrl(tid, pg, merged);
    var html = await httpGet(url);
    var result = parseVodList(html);
    return JSON.stringify({ list: result.list, pagecount: result.pagecount });
  } catch (e) {
    console.error("分类失败:", e.message);
    return JSON.stringify({ list: [], pagecount: 0 });
  }
}

async function search(wd, quick, page) {
  page = page || 1;
  try {
    var kw = String(wd || '').trim();
    if (!kw) return JSON.stringify({ list: [], pagecount: 0 });
    var url = buildSearchUrl(kw, page);
    var html = await httpGet(url);
    if (!html) return JSON.stringify({ list: [], pagecount: 0 });
    var result = parseSearchList(html);
    return JSON.stringify({ list: result.list, pagecount: result.pagecount });
  } catch (e) {
    console.error("搜索失败:", e.message);
    return JSON.stringify({ list: [], pagecount: 0 });
  }
}

async function detail(id) {
  try {
    var detailUrl = id.indexOf('http') === 0 ? id : appConfig.siteUrl + '/voddetail/' + String(id).replace(/^\//, '') + '.html';
    var html = await httpGet(detailUrl);
    if (!html) return JSON.stringify({ list: [] });
    var $ = cheerio.load(html);

    var vod_name = '';
    // shoutu45 模板无 h1, 从 title 或 class 含 title 的元素提取
    var h1 = $('h1').first().text().trim();
    if (h1) vod_name = h1;
    if (!vod_name) {
      var titleTag = $('title').text().trim();
      var tm = titleTag.match(/《([^》]+)》/);
      vod_name = tm ? tm[1] : titleTag.replace(/[-_—].*$/, '').trim();
    }
    if (!vod_name) {
      vod_name = $('.detail-title, .title, .module-info-heading h2, .content-title').first().text().trim();
    }

    var pic = '';
    // shoutu45 模板: 封面图在 .this-bj / .this-pic-bj 的 CSS background-image 中
    $('.this-bj, .this-pic-bj').each(function() {
      var style = $(this).attr('style') || '';
      var bm = style.match(/background-image\s*:\s*url\(["']?([^"')\s]+)/i);
      if (bm && bm[1]) { pic = bm[1]; return false; }
    });
    // 备选: img[data-src] 但排除推荐列表中的图片
    if (!pic) {
      var mainImg = $('img.gen-movie-img').first();
      if (mainImg.length) {
        pic = mainImg.attr('data-src') || mainImg.attr('src') || '';
      }
    }
    if (!pic) {
      var picEl = $('.detail-pic img, .module-info-poster img, .stui-content__thumb img').first();
      pic = picEl.attr('data-src') || picEl.attr('src') || '';
    }
    if (!pic) pic = $('meta[property="og:image"]').attr('content') || '';
    pic = normalizePic(pic);

    var vod_year = '', vod_area = '', vod_class = '', vod_director = '', vod_actor = '',
      vod_lang = '', vod_remarks = '', vod_content = '';

    // shoutu45 模板: <li><em class="cor4">字段：</em>值</li>
    $('li, .detail-info-item, .module-info-item').each(function() {
      var el = $(this);
      var em = el.find('em.cor4, .module-info-item-title, .label, em').first();
      var key = em.text().replace(/[：:]/g, '').trim();
      if (!key) return;
      // 取 em 之后的内容作为值
      var val = el.clone();
      val.find('em.cor4, .module-info-item-title, .label, em').remove();
      val.find('i, span.badge').remove();
      val = val.text().replace(/[\s\n\r]+/g, ' ').trim().replace(/\/+$/, '').trim();
      if (!val) return;
      if (key.indexOf('导演') !== -1) vod_director = val || vod_director;
      else if (key.indexOf('主演') !== -1 || key.indexOf('演员') !== -1) vod_actor = val || vod_actor;
      else if (key.indexOf('类型') !== -1) vod_class = val || vod_class;
      else if (key.indexOf('地区') !== -1 || key.indexOf('国家') !== -1) vod_area = val || vod_area;
      else if (key.indexOf('年份') !== -1) { var ym = val.match(/(\d{4})/); if (ym) vod_year = ym[1]; }
      else if (key.indexOf('语言') !== -1) vod_lang = val || vod_lang;
      else if (key.indexOf('状态') !== -1 || key.indexOf('备注') !== -1) vod_remarks = val || vod_remarks;
      else if (key.indexOf('更新') !== -1) { if (!vod_remarks) vod_remarks = val; }
      else if (key.indexOf('简介') !== -1 || key.indexOf('剧情') !== -1) vod_content = val || vod_content;
    });

    // 备选: 从常见简介容器提取（shoutu45 模板无此 class，作为兜底）
    if (!vod_content) {
      vod_content = $('.detail-content, .module-info-introduction-content, .detail-desc, .content, .this-desc-body, .juqing').first().text().replace(/[\s\n\r]+/g, ' ').trim();
    }
    if (vod_content) vod_content = vod_content.substring(0, 500);

    // 播放线路与剧集
    // 线路名: anthology-tab 区域 (去掉 i 图标和 span.badge 集数)
    // 不过滤"下载"线路名，确保与播放列表一一对应
    var lineNames = [];
    $('.anthology-tab a, .anthology-tab li').each(function() {
      var el = $(this).clone();
      el.find('i, span.badge, .badge').remove();
      var t = el.text().replace(/[\s\n\r]+/g, ' ').replace(/&nbsp;/g, '').trim();
      if (t) lineNames.push(t);
    });

    // 播放列表: 每个 anthology-list-play 或 anthology-list-box 内的 a 标签
    var groupLists = [];
    $('.anthology-list-play').each(function() {
      var eps = [];
      $(this).find('a[href*="/vodplay/"]').each(function() {
        var epName = $(this).text().replace(/[\s\n\r]+/g, ' ').trim();
        var epUrl = $(this).attr('href') || '';
        if (epUrl && epName && epUrl.indexOf('/vodplay/') !== -1) {
          if (!epUrl.startsWith('http')) epUrl = appConfig.siteUrl + epUrl;
          eps.push(epName + '$' + epUrl);
        }
      });
      if (eps.length > 0) groupLists.push(eps);
    });

    // 备选: 如果 anthology-list-play 没找到, 尝试 .anthology-list-box
    if (groupLists.length === 0) {
      $('.anthology-list-box').each(function() {
        var eps = [];
        $(this).find('a[href*="/vodplay/"]').each(function() {
          var epName = $(this).text().replace(/[\s\n\r]+/g, ' ').trim();
          var epUrl = $(this).attr('href') || '';
          if (epUrl && epName && epUrl.indexOf('/vodplay/') !== -1) {
            if (!epUrl.startsWith('http')) epUrl = appConfig.siteUrl + epUrl;
            eps.push(epName + '$' + epUrl);
          }
        });
        if (eps.length > 0) groupLists.push(eps);
      });
    }

    if (groupLists.length === 0) {
      lineNames.push('默认线路');
      groupLists.push(['暂无播放地址$' + id]);
    }
    // 确保线路名与播放列表数量一致
    if (lineNames.length === 0) {
      for (var i = 0; i < groupLists.length; i++) lineNames.push('线路' + (i + 1));
    }
    // 线路名多于播放列表: 截断线路名
    if (lineNames.length > groupLists.length) lineNames.length = groupLists.length;
    // 线路名少于播放列表: 补充默认名
    while (lineNames.length < groupLists.length) lineNames.push('线路' + (lineNames.length + 1));

    var vod_play_from = lineNames.join('$$$');
    var vod_play_url = groupLists.map(function(g) { return g.join('#'); }).join('$$$');

    return JSON.stringify({ list: [{
      vod_id: String(id), vod_name: vod_name, vod_pic: pic,
      vod_actor: vod_actor, vod_director: vod_director,
      vod_remarks: vod_remarks, vod_year: vod_year, vod_area: vod_area,
      vod_lang: vod_lang, vod_content: vod_content, vod_class: vod_class,
      vod_play_from: vod_play_from, vod_play_url: vod_play_url
    }] });
  } catch (e) {
    console.error("详情失败:", e.message);
    return JSON.stringify({ list: [] });
  }
}

// ============ 播放 ============
async function play(flag, id, flags) {
  var Header = { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' };
  try {
    var src = String(id || '').trim();
    if (/\.(m3u8|mp4)(\?|$)/i.test(src)) {
      return JSON.stringify({ parse: 0, url: src, Header: Header });
    }
    var playPageUrl = src.indexOf('http') === 0 ? src : appConfig.siteUrl + '/' + src.replace(/^\//, '');
    var html = await httpGet(playPageUrl);
    if (!html) return JSON.stringify({ parse: 1, Header: Header, url: playPageUrl });

    var realUrl = '';
    var pIdx = html.indexOf('player_aaaa');
    if (pIdx !== -1) {
      var eq = html.indexOf('{', pIdx);
      if (eq !== -1) {
        var depth = 0, inStr = false, esc = false, objText = '';
        for (var i = eq; i < html.length; i++) {
          var c = html[i];
          if (inStr) {
            if (esc) esc = false;
            else if (c === '\\') esc = true;
            else if (c === '"') inStr = false;
          } else {
            if (c === '"') inStr = true;
            else if (c === '{') depth++;
            else if (c === '}') { depth--; if (depth === 0) { objText = html.slice(eq, i + 1); break; } }
          }
        }
        if (objText) {
          try {
            var player = JSON.parse(objText);
            var url = player.url || '';
            var encrypt = player.encrypt || 0;
            if (url) {
              if (encrypt === 1) { try { url = atob(url); } catch (e) {} }
              else if (encrypt === 2) { url = decodeEncrypt2(url); }
              realUrl = url;
            }
          } catch (e) { console.error("解析player_aaaa失败:", e.message); }
        }
      }
    }

    if (!realUrl) {
      var m3 = html.match(/(https?:\/\/[^\s"'<>]+?\.(m3u8|mp4)[^\s"'<>]*)/);
      if (m3) realUrl = m3[1].replace(/\\\//g, '/');
    }

    if (realUrl && /\.(m3u8|mp4)(\?|$)/i.test(realUrl)) {
      return JSON.stringify({ parse: 0, url: realUrl, Header: Header });
    }
    if (realUrl && /^https?:\/\//i.test(realUrl)) {
      return JSON.stringify({ parse: 1, url: realUrl, Header: Header });
    }
    return JSON.stringify({ parse: 1, Header: Header, url: playPageUrl });
  } catch (e) {
    console.error("播放失败:", e.message);
    return JSON.stringify({ parse: 1, Header: Header, url: String(id || '') });
  }
}

function decodeEncrypt2(str) {
  try {
    var bin = atob(str);
    var decoded = decodeURIComponent(bin);
    return decoded;
  } catch (e) {
    try { return decodeURIComponent(atob(str)); } catch (e2) { return str; }
  }
}

export default { init: init, home: home, category: category, detail: detail, search: search, play: play };
