// ============================================================
// VocabBuddy 数据层 · 真实/参考型数据（长期有效）
// 通过 <script src="data.js"></script> 同步注入 window.APP_DATA。
// 这里只放「与用户后端无关、不会随学习记录变化」的静态内容：
//   - 应用常量（名称、默认昵称）
//   - 单词字典（学习内容本体）
//   - 可选词库列表（参考项）
// 会随用户行为/学习记录变化的「设置、统计、生词本」由后端 API（MySQL）实时提供，不再使用本地假数据文件。
// ============================================================
window.APP_DATA = {
  "app": {
    "name": "VocabBuddy",
    "userName": "同学"
  },
  "words": [
    {"en":"academy",   "phonetic":"/əˈkædəmi/",    "pos":"n.",   "cn":"学院，研究院",        "example":"She won a scholarship to the art academy."},
    {"en":"abundant",  "phonetic":"/əˈbʌndənt/",   "pos":"adj.", "cn":"丰富的，充裕的",      "example":"The region has abundant natural resources."},
    {"en":"accomplish","phonetic":"/əˈkʌmplɪʃ/",   "pos":"v.",   "cn":"完成，实现",          "example":"We accomplished our goal ahead of schedule."},
    {"en":"accurate",  "phonetic":"/ˈækjərət/",    "pos":"adj.", "cn":"准确的，精确的",      "example":"Please give me an accurate figure."},
    {"en":"acquire",   "phonetic":"/əˈkwaɪər/",    "pos":"v.",   "cn":"获得，取得",          "example":"He acquired a good knowledge of French."},
    {"en":"adequate",  "phonetic":"/ˈædɪkwət/",    "pos":"adj.", "cn":"足够的，适当的",      "example":"The food was adequate for our needs."},
    {"en":"adjacent",  "phonetic":"/əˈdʒeɪsnt/",   "pos":"adj.", "cn":"邻近的，相邻的",      "example":"The garden is adjacent to the house."},
    {"en":"ambitious", "phonetic":"/æmˈbɪʃəs/",   "pos":"adj.", "cn":"有雄心的，野心勃勃的","example":"She has an ambitious plan for the company."},
    {"en":"analyze",   "phonetic":"/ˈænəlaɪz/",    "pos":"v.",   "cn":"分析，解析",          "example":"We need to analyze the results carefully."},
    {"en":"anticipate","phonetic":"/ænˈtɪsɪpeɪt/", "pos":"v.",   "cn":"预期，预料",          "example":"We anticipate a rise in prices."},
    {"en":"apparent",  "phonetic":"/əˈpærənt/",    "pos":"adj.", "cn":"明显的，表面的",      "example":"It was apparent that he was tired."},
    {"en":"appreciate","phonetic":"/əˈpriːʃieɪt/","pos":"v.",   "cn":"欣赏，感激",          "example":"I appreciate your help very much."},
    {"en":"appropriate","phonetic":"/əˈproʊpriət/","pos":"adj.","cn":"适当的，合适的",      "example":"Choose clothing appropriate to the weather."},
    {"en":"arithmetic","phonetic":"/əˈrɪθmətɪk/", "pos":"n.",   "cn":"算术，算法",          "example":"He is good at mental arithmetic."},
    {"en":"assemble",  "phonetic":"/əˈsembl/",     "pos":"v.",   "cn":"集合，装配",          "example":"We assembled the furniture in an hour."},
    {"en":"assume",    "phonetic":"/əˈsuːm/",      "pos":"v.",   "cn":"假定，承担",          "example":"I assume you have read the report."},
    {"en":"attribute", "phonetic":"/əˈtrɪbjuːt/", "pos":"v.",   "cn":"归因于，属性",        "example":"She attributes her success to hard work."},
    {"en":"audience",  "phonetic":"/ˈɔːdiəns/",   "pos":"n.",   "cn":"观众，听众",          "example":"The audience applauded loudly."},
    {"en":"authentic", "phonetic":"/ɔːˈθentɪk/",  "pos":"adj.", "cn":"真实的，正宗的",      "example":"This is an authentic Italian recipe."},
    {"en":"available", "phonetic":"/əˈveɪləbl/",  "pos":"adj.", "cn":"可获得的，可用的",    "example":"Tickets are available online."}
  ],
  "libraryOptions": [
    {"name":"CET-4 四级", "ic":"📘", "code":"cet4"},
    {"name":"CET-6 六级", "ic":"📗", "code":"cet6"},
    {"name":"考研词汇",    "ic":"🎓", "code":"kaoyan"},
    {"name":"SAT",          "ic":"🎯", "code":"sat"},
    {"name":"托福 TOEFL",  "ic":"🗽", "code":"toefl"}
  ]
};
