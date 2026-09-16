//  >>> 当前时间是：2026-06-17 09:51:23 <<<
//  当前接口：https://ym.wya6.cn/xsa/js/腾讯视频.js

var rule = {
    title: '腾讯视频',
    host: 'https://v.qq.com',
    homeUrl: '',
    searchUrl: '**',
    searchable: 2,
    filterable: 1,
    multi: 1,
    class_name: '电视剧&电影&综艺&纪录片&动漫&少儿&短剧&体育&宠物TV&中视频&音乐',
    class_url: '100113&100173&100109&100105&100119&100150&110755&100103&100302&110852&100118',
    filter: {
        "100113": [
            {
                "key": "sort",
                "name": "排序",
                "value": [
                    { "n": "最热", "v": "75" },
                    { "n": "最新上架", "v": "79" },
                    { "n": "高分好评", "v": "85" }
                ]
            },
            {
                "key": "itype",
                "name": "类型",
                "value": [
                    { "n": "全部", "v": "-1" },
                    { "n": "爱情", "v": "1" },
                    { "n": "都市", "v": "2" },
                    { "n": "青春", "v": "3" },
                    { "n": "奇幻", "v": "4" },
                    { "n": "武侠", "v": "5" },
                    { "n": "古装", "v": "6" },
                    { "n": "科幻", "v": "7" },
                    { "n": "悬疑", "v": "14" },
                    { "n": "喜剧", "v": "13" }
                ]
            },
            {
                "key": "ipay",
                "name": "资费",
                "value": [
                    { "n": "全部", "v": "-1" },
                    { "n": "免费", "v": "1" },
                    { "n": "会员", "v": "3" }
                ]
            },
            {
                "key": "iarea",
                "name": "地区",
                "value": [
                    { "n": "全部", "v": "-1" },
                    { "n": "内地", "v": "0" },
                    { "n": "中国香港", "v": "14" },
                    { "n": "美国", "v": "8" },
                    { "n": "韩国", "v": "5" },
                    { "n": "日本", "v": "10" }
                ]
            },
            {
                "key": "iyear",
                "name": "年份",
                "value": [
                    { "n": "全部", "v": "-1" },
                    { "n": "2026", "v": "2026" },
                    { "n": "2025", "v": "2025" },
                    { "n": "2024", "v": "2" },
                    { "n": "2023", "v": "3" },
                    { "n": "2022", "v": "4" },
                    { "n": "2021", "v": "5" }
                ]
            }
        ],
        "100173": [
            {
                "key": "sort",
                "name": "排序",
                "value": [
                    { "n": "最热", "v": "75" },
                    { "n": "最新", "v": "83" },
                    { "n": "高分", "v": "81" }
                ]
            },
            {
                "key": "itype",
                "name": "类型",
                "value": [
                    { "n": "全部", "v": "-1" },
                    { "n": "动作", "v": "4" },
                    { "n": "喜剧", "v": "3" },
                    { "n": "爱情", "v": "5" },
                    { "n": "科幻", "v": "12" },
                    { "n": "悬疑", "v": "10" }
                ]
            },
            {
                "key": "iarea",
                "name": "地区",
                "value": [
                    { "n": "全部", "v": "-1" },
                    { "n": "内地", "v": "100024" },
                    { "n": "中国香港", "v": "100025" },
                    { "n": "美国", "v": "100029" }
                ]
            }
        ],
        "100109": [],
        "100105": [],
        "100119": [],
        "100150": [],
        "110755": [],
        "100103": [],
        "100302": [],
        "110852": [],
        "100118": []
    },
    headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5410.0 Safari/537.36',
        'origin': 'https://v.qq.com',
        'referer': 'https://v.qq.com/'
    },
    timeout: 5000,
    play_parse: true,
    lazy: $js.toString(() => {
        let url = input;
        if (url.includes('v.qq.com')) {
            url = 'https://jx.xmflv.com/?url=' + encodeURIComponent(url);
        }
        input = {
            parse: 0,
            url: url,
            header: {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5410.0 Safari/537.36'
            }
        };
    }),

    一级: $js.toString(() => {
        let d = [];
        let tid = MY_CATE;
        let pg = MY_PAGE;
        let extend = MY_FL || {};

        // 新版频道 ID
        const newChannelIds = ['100103', '100302', '110852', '100118'];

        if (newChannelIds.includes(tid)) {
            // 新版频道逻辑
            let cacheKey = 'tencent_ctx_' + tid;
            let pageContext = null;
            if (pg > 1) {
                try {
                    let cached = storage0.getItem(cacheKey);
                    if (cached) {
                        let obj = JSON.parse(cached);
                        if (obj.page === pg - 1 && obj.nextContext) {
                            pageContext = obj.nextContext;
                        }
                    }
                } catch (e) {}
            } else {
                storage0.setItem(cacheKey, '');
            }

            let body = {
                'page_params': {
                    'page_type': 'channel',
                    'page_id': tid,
                    'scene': 'channel',
                    'new_mark_label_enabled': '1',
                    'vl_to_mvl': '',
                    'ad_exp_ids': '',
                    'ams_cookies': '',
                    'ad_trans_data': '{}',
                    'skip_privacy_types': '0',
                    'support_click_scan': '1'
                },
                'page_bypass_params': {
                    'params': {
                        'platform_id': '2',
                        'caller_id': '3000010',
                        'data_mode': 'default',
                        'user_mode': 'default',
                        'specified_strategy': '',
                        'page_type': 'channel',
                        'page_id': tid,
                        'scene': 'channel',
                        'new_mark_label_enabled': '1'
                    },
                    'scene': 'channel',
                    'app_version': '',
                    'abtest_bypass_id': ''
                },
                'page_context': pageContext
            };

            try {
                let html = request('https://pbaccess.video.qq.com/trpc.vector_layout.page_view.PageService/getPage?video_appid=3000010&vversion_platform=2', {
                    body: JSON.stringify(body),
                    headers: {
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5410.0 Safari/537.36',
                        'Content-Type': 'application/json',
                        'Origin': 'https://v.qq.com',
                        'Referer': 'https://v.qq.com/'
                    },
                    method: 'POST'
                });
                let json = JSON.parse(html);
                let data = json.data || {};

                if (data.has_next_page && data.page_context) {
                    storage0.setItem(cacheKey, JSON.stringify({
                        page: pg,
                        nextContext: data.page_context
                    }));
                }

                let cardList = data.CardList || [];
                cardList.forEach(function(module) {
                    let cards = (module.children_list && module.children_list.list && module.children_list.list.cards) || [];
                    cards.forEach(function(card) {
                        let params = card.params || {};
                        let cid = params.cid;
                        if (!cid) return;
                        let name = params.mz_title || params.title || params.material_video_title;
                        if (!name) return;
                        let pic = params.image_url_vertical || params.pic_496x280 || params.pic496x280 || params.pic_540x304 || params.image_url || params.pic_750x422 || '';
                        let remarks = params.episode_updated || params.material_video_subtitle || params.update_title || params.rec_normal_reason || '';
                        d.push({
                            vod_id: cid,
                            vod_name: name,
                            vod_pic: pic,
                            vod_remarks: remarks
                        });
                    });
                });
            } catch (e) {
                log('新版频道请求失败: ' + e.message);
            }
            setResult(d);
            return;
        }

        // 普通频道逻辑
        let params = {
            sort: extend.sort || '75',
            attr: extend.attr || '-1',
            itype: extend.itype || '-1',
            ipay: extend.ipay || '-1',
            iarea: extend.iarea || '-1',
            iyear: extend.iyear || '-1',
            theater: extend.theater || '-1',
            award: extend.award || '-1',
            recommend: extend.recommend || '-1'
        };
        let filterParams = [];
        for (let k in params) {
            filterParams.push(k + '=' + params[k]);
        }
        let filterStr = filterParams.join('&');

        let pageContext = '';
        let cacheKey = 'tencent_normal_ctx_' + tid + '_' + filterStr;
        if (pg > 1) {
            try {
                let cached = storage0.getItem(cacheKey);
                if (cached) {
                    let obj = JSON.parse(cached);
                    if (obj.page === pg - 1 && obj.nextContext) {
                        pageContext = obj.nextContext;
                    }
                }
            } catch (e) {}
        } else {
            storage0.setItem(cacheKey, '');
        }

        let body = {
            "page_params": {
                "channel_id": tid,
                "filter_params": filterStr,
                "page_type": "channel_operation",
                "page_id": "channel_list_second_page"
            },
            "page_context": pageContext
        };

        try {
            let html = request('https://pbaccess.video.qq.com/trpc.universal_backend_service.page_server_rpc.PageServer/GetPageData?video_appid=1000005&vplatform=2&vversion_name=8.9.10&new_mark_label_enabled=1', {
                body: JSON.stringify(body),
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5410.0 Safari/537.36',
                    'Content-Type': 'application/json',
                    'Origin': 'https://v.qq.com',
                    'Referer': 'https://v.qq.com/'
                },
                method: 'POST'
            });
            let json = JSON.parse(html);
            let ndata = json.data || {};

            if (ndata.has_next_page && ndata.next_page_context) {
                storage0.setItem(cacheKey, JSON.stringify({
                    page: pg,
                    nextContext: ndata.next_page_context
                }));
            }

            let itemDatas = [];
            try {
                itemDatas = ndata.module_list_datas[ndata.module_list_datas.length - 1]
                    .module_datas[ndata.module_datas.length - 1]
                    .item_data_lists.item_datas;
            } catch (e) {
                // 尝试通用遍历
                function findItemDatas(obj) {
                    if (!obj) return;
                    if (obj.item_data_lists && obj.item_data_lists.item_datas) {
                        itemDatas = obj.item_data_lists.item_datas;
                        return;
                    }
                    for (let k in obj) {
                        if (typeof obj[k] === 'object') findItemDatas(obj[k]);
                    }
                }
                findItemDatas(ndata);
            }

            itemDatas.forEach(function(item) {
                let p = item.item_params || {};
                let cid = p.cid;
                if (!cid) return;
                let name = p.mz_title || p.title;
                if (!name) return;
                let pic = p.new_pic_hz || p.new_pic_vt || p.image_url || '';
                let tag = {};
                try {
                    tag = JSON.parse(p.uni_imgtag || p.imgtag || '{}');
                } catch (e) {}
                let year = tag.tag_2 ? tag.tag_2.text : '';
                let remarks = tag.tag_4 ? tag.tag_4.text : '';
                d.push({
                    vod_id: cid,
                    vod_name: name,
                    vod_pic: pic,
                    vod_year: year,
                    vod_remarks: remarks
                });
            });
        } catch (e) {
            log('分类请求失败: ' + e.message);
        }

        setResult(d);
    }),

    二级: $js.toString(() => {
        VOD = {};
        let cid = input;
        if (!cid) return;

        let apihost = 'https://pbaccess.video.qq.com';

        // 请求详情
        let vbody = {
            "page_params": {
                "req_from": "web",
                "cid": cid,
                "vid": "",
                "lid": "",
                "page_type": "detail_operation",
                "page_id": "detail_page_introduction"
            },
            "has_cache": 1
        };

        // 请求剧集列表
        let body = {
            "page_params": {
                "req_from": "web_vsite",
                "page_id": "vsite_episode_list",
                "page_type": "detail_operation",
                "id_type": "1",
                "page_size": "",
                "cid": cid,
                "vid": "",
                "lid": "",
                "page_num": "",
                "page_context": "",
                "detail_page_type": "1"
            },
            "has_cache": 1
        };

        let vdata = null;
        let data = null;

        try {
            let vhtml = request(apihost + '/trpc.universal_backend_service.page_server_rpc.PageServer/GetPageData?video_appid=3000010&vplatform=2&vversion_name=8.2.96', {
                body: JSON.stringify(vbody),
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5410.0 Safari/537.36',
                    'Content-Type': 'application/json',
                    'Origin': 'https://v.qq.com',
                    'Referer': 'https://v.qq.com/'
                },
                method: 'POST'
            });
            vdata = JSON.parse(vhtml);
        } catch (e) {
            log('详情请求失败: ' + e.message);
        }

        try {
            let html = request(apihost + '/trpc.universal_backend_service.page_server_rpc.PageServer/GetPageData?video_appid=3000010&vplatform=2&vversion_name=8.2.96', {
                body: JSON.stringify(body),
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5410.0 Safari/537.36',
                    'Content-Type': 'application/json',
                    'Origin': 'https://v.qq.com',
                    'Referer': 'https://v.qq.com/'
                },
                method: 'POST'
            });
            data = JSON.parse(html);
        } catch (e) {
            log('剧集请求失败: ' + e.message);
        }

        // 解析详情
        let actors = [];
        if (vdata && vdata.data && vdata.data.module_list_datas) {
            try {
                let dItem = vdata.data.module_list_datas[0].module_datas[0].item_data_lists.item_datas[0];
                let p = dItem.item_params || {};
                VOD.vod_name = p.title || '';
                VOD.vod_year = p.year || '';
                VOD.vod_area = p.area_name || '';
                VOD.vod_remarks = p.holly_online_time || p.hotval || '';
                VOD.vod_content = p.cover_description || '';
                VOD.type_name = p.sub_genre || '';
                // 演员
                let starList = dItem.sub_items && dItem.sub_items.star_list && dItem.sub_items.star_list.item_datas || [];
                actors = starList.map(function(s) { return s.item_params.name; }).filter(Boolean);
                VOD.vod_actor = actors.join(',');
            } catch (e) {}
        }

        // 解析剧集
        let plist = [];
        let ylist = [];
        if (data && data.data && data.data.module_list_datas) {
            try {
                let items = data.data.module_list_datas[data.data.module_list_datas.length - 1]
                    .module_datas[data.data.module_datas.length - 1]
                    .item_data_lists.item_datas;
                items.forEach(function(item) {
                    let itemId = item.item_id;
                    let p = item.item_params || {};
                    let title = p.union_title || '';
                    if (!itemId || !title) return;
                    let playUrl = 'https://v.qq.com/x/cover/' + cid + '/' + itemId + '.html';
                    let parseUrl = 'https://jx.xmflv.com/?url=' + encodeURIComponent(playUrl);
                    let entry = title + '$' + parseUrl;
                    if (title.includes('预告')) {
                        ylist.push(entry);
                    } else {
                        plist.push(entry);
                    }
                });
            } catch (e) {
                log('剧集解析失败: ' + e.message);
            }
        }

        let froms = [];
        let urls = [];
        if (plist.length > 0) {
            froms.push('腾讯视频');
            urls.push(plist.join('#'));
        }
        if (ylist.length > 0) {
            froms.push('预告片');
            urls.push(ylist.join('#'));
        }
        if (froms.length === 0) {
            froms.push('腾讯视频');
            urls.push('正片$https://v.qq.com/x/cover/' + cid + '.html');
        }

        VOD.vod_play_from = froms.join('$$$');
        VOD.vod_play_url = urls.join('$$$');
        if (!VOD.vod_name) VOD.vod_name = cid;
    }),

    搜索: $js.toString(() => {
        let d = [];
        let key = input.split('/')[3] || input;
        let pg = input.split('/')[4] || '1';
        let body = {
            "version": "24072901",
            "clientType": 1,
            "filterValue": "",
            "uuid": "B1E50847-D25F-4C4B-BBA0-36F0093487F6",
            "retry": 0,
            "query": key,
            "pagenum": parseInt(pg) - 1,
            "pagesize": 30,
            "queryFrom": 0,
            "searchDatakey": "",
            "transInfo": "",
            "isneedQc": true,
            "preQid": "",
            "adClientInfo": "",
            "extraInfo": {
                "isNewMarkLabel": "1",
                "multi_terminal_pc": "1"
            }
        };

        try {
            let html = request('https://pbaccess.video.qq.com/trpc.videosearch.mobile_search.MultiTerminalSearch/MbSearch?vplatform=2', {
                body: JSON.stringify(body),
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.5410.0 Safari/537.36',
                    'Content-Type': 'application/json',
                    'Origin': 'https://v.qq.com',
                    'Referer': 'https://v.qq.com/'
                },
                method: 'POST'
            });
            let json = JSON.parse(html);
            let areaBoxList = json.data && json.data.areaBoxList || [];
            let lastBox = areaBoxList[areaBoxList.length - 1] || {};
            let itemList = lastBox.itemList || [];
            itemList.forEach(function(it) {
                if (it.doc && it.doc.id) {
                    let videoInfo = it.videoInfo || {};
                    let imgTag = {};
                    try {
                        imgTag = JSON.parse(videoInfo.imgTag || '{}');
                    } catch (e) {}
                    let pic = videoInfo.imgUrl || '';
                    d.push({
                        vod_id: it.doc.id,
                        vod_name: videoInfo.title || '',
                        vod_pic: pic,
                        vod_year: imgTag.tag_2 ? imgTag.tag_2.text : '',
                        vod_remarks: imgTag.tag_4 ? imgTag.tag_4.text : ''
                    });
                }
            });
        } catch (e) {
            log('搜索失败: ' + e.message);
        }
        setResult(d);
    })
};