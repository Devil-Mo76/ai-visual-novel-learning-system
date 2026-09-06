"""演示模式离线样例数据（答辩断网/无 Key 时用的降级数据源）。

包含：
- SAMPLE_DOCUMENT：一份带若干知识点的样例学习资料（纯文本）。
- SAMPLE_SCRIPT：与该资料对应的分章教学剧本（ScriptPayload 形状的 chapters，
  覆盖 6 个背景 key，每章末尾 1 道题，choice/fill/short 三种题型齐备）。
- SAMPLE_ANALYTICS：几行作答记录（有对有错），供「学习报告」「错题本」演示。

用途：
1. migrate.py 在数据库为空且用户为种子时幂等导入（未登录/演示账号立即有数据）。
2. 演示模式（Settings.demo_mode=True）下，生成/判题/讲师不调 AI，直接用这里的数据。
"""

SAMPLE_DOCUMENT_TITLE = "操作系统基础（演示资料）"
SAMPLE_DOCUMENT_CONTENT = """这里是《操作系统基础》演示资料的主要内容。

【进程】进程是程序的一次运行活动，是系统进行资源分配和调度的基本单位。进程与程序不同：
程序是静态的指令集合，进程是动态的执行过程。进程有三个基本状态：就绪、运行、阻塞。

【线程】线程是进程内的一个执行单元，是 CPU 调度的基本单位。一个进程可以包含多个线程，
它们共享进程的地址空间和资源，线程切换比进程切换开销更小。

【死锁】死锁是指两个或多个进程互相等待对方持有的资源而无法继续推进的状态。
产生死锁需要四个必要条件：互斥、持有并等待、不可剥夺、循环等待。死锁的处理方法：
预防、避免（银行家算法）、检测与解除。

【存储管理】内存管理的主要功能包括分配与回收、地址转换、内存保护。页式存储管理
把内存与进程地址空间划分为大小相等的页，通过页表完成逻辑地址到物理地址的转换。

【文件系统】文件系统负责磁盘上文件的组织、存储与访问。常见的文件组织方式有顺序、
索引与散列。目录采用树形结构，方便按名存取与分层管理。

【磁盘调度】磁盘读写需要考虑寻道时间，常用调度算法有先来先服务（FCFS）、
最短寻道时间优先（SSTF）、扫描算法（SCAN）。不同的调度算法在响应时间与寻道总量上各有取舍。
"""

# —— 样例剧本：6 章，每章一个知识点，覆盖 6 个背景 key ——
SAMPLE_SCRIPT = {
    "title": "操作系统基础（演示剧本）",
    "source": SAMPLE_DOCUMENT_TITLE,
    "chapters": [
        {
            "id": "ch_1",
            "title": "初识进程",
            "background": "客厅",
            "steps": [
                {"type": "line", "speaker": "teacher", "text": "先把进程和程序分清楚，这是理解操作系统的第一步。",
                 "talk_emo": "jiangjie", "listen_emo": "sikao"},
                {"type": "line", "speaker": "student", "text": "诶？进程和程序不是一回事吗？",
                 "talk_emo": "tiwen", "listen_emo": "kunhuo"},
                {"type": "line", "speaker": "teacher", "text": "程序是静态的指令集合，进程是它的一次运行活动。",
                 "talk_emo": "yansu", "listen_emo": "sikao"},
                {"type": "line", "speaker": "student", "text": "哦，程序像菜谱，进程是把菜做出来的过程？",
                 "talk_emo": "huangrandawu", "listen_emo": "gaoxing"},
                {"type": "line", "speaker": "teacher", "text": "对，进程也是资源分配和调度的基本单位。",
                 "talk_emo": "gaoxing", "listen_emo": "tingdongle"},
                {"type": "line", "speaker": "teacher", "text": "它有三个基本状态：就绪、运行、阻塞。",
                 "talk_emo": "jiangjie", "listen_emo": "sikao"},
                {"type": "question", "speaker": "teacher", "text": "下面哪个状态不是进程的基本状态？",
                 "talk_emo": "yansu", "listen_emo": "sikao",
                 "quiz_type": "choice", "choices": ["就绪", "运行", "阻塞", "终止"], "answer": 3,
                 "explain": "进程三态是就绪、运行、阻塞；终止是生命周期终点的状态，不算基本三态。"},
            ],
        },
        {
            "id": "ch_2",
            "title": "线程与轻量化",
            "background": "河流树木",
            "steps": [
                {"type": "line", "speaker": "teacher", "text": "线程是进程内的执行单元，是 CPU 调度的基本单位。",
                 "talk_emo": "jiangjie", "listen_emo": "sikao"},
                {"type": "line", "speaker": "student", "text": "那线程和进程的关系到底怎么记？",
                 "talk_emo": "tiwen", "listen_emo": "kunhuo"},
                {"type": "line", "speaker": "teacher", "text": "一个进程可以包含多个线程，它们共享进程的地址空间。",
                 "talk_emo": "jiangjie", "listen_emo": "gaoxing"},
                {"type": "line", "speaker": "student", "text": "共享资源岂不是方便很多？",
                 "talk_emo": "huangrandawu", "listen_emo": "gaoxing"},
                {"type": "question", "speaker": "teacher", "text": "线程切换比进程切换开销______。",
                 "talk_emo": "yansu", "listen_emo": "sikao",
                 "quiz_type": "fill", "answer_text": "更小",
                 "explain": "线程共享地址空间，切换无需切换内存映射，开销比进程切换更小。"},
            ],
        },
        {
            "id": "ch_3",
            "title": "死锁四大条件",
            "background": "破旧房间",
            "steps": [
                {"type": "line", "speaker": "teacher", "text": "死锁是进程互相等待资源、谁也推进不了的状态。",
                 "talk_emo": "jiangjie", "listen_emo": "sikao"},
                {"type": "line", "speaker": "student", "text": "听起来很可怕，它怎么发生的？",
                 "talk_emo": "tiwen", "listen_emo": "kunhuo"},
                {"type": "line", "speaker": "teacher", "text": "触发死锁需要四个条件同时成立。",
                 "talk_emo": "yansu", "listen_emo": "sikao"},
                {"type": "question", "speaker": "teacher", "text": "请说出死锁产生的必要条件。",
                 "talk_emo": "yansu", "listen_emo": "sikao",
                 "quiz_type": "short", "reference_points": ["互斥", "持有并等待", "不可剥夺", "循环等待"],
                 "explain": "四个条件：互斥、持有并等待、不可剥夺、循环等待。"},
            ],
        },
        {
            "id": "ch_4",
            "title": "页式存储",
            "background": "紫色河流树木",
            "steps": [
                {"type": "line", "speaker": "teacher", "text": "内存管理要做分配回收、地址转换、和内存保护。",
                 "talk_emo": "jiangjie", "listen_emo": "sikao"},
                {"type": "line", "speaker": "student", "text": "地址转换是什么意思？",
                 "talk_emo": "tiwen", "listen_emo": "kunhuo"},
                {"type": "line", "speaker": "teacher", "text": "页式存储把内存划成等大的页，用页表做逻辑地址到物理地址的转换。",
                 "talk_emo": "jiangjie", "listen_emo": "tingdongle"},
                {"type": "question", "speaker": "teacher", "text": "页式存储管理中，负责地址转换的是______。",
                 "talk_emo": "yansu", "listen_emo": "sikao",
                 "quiz_type": "fill", "answer_text": "页表",
                 "explain": "页表记录逻辑页与物理页帧的映射，完成地址转换。"},
            ],
        },
        {
            "id": "ch_5",
            "title": "文件系统",
            "background": "草地",
            "steps": [
                {"type": "line", "speaker": "teacher", "text": "文件系统负责磁盘上文件的组织、存储与访问。",
                 "talk_emo": "jiangjie", "listen_emo": "sikao"},
                {"type": "line", "speaker": "student", "text": "文件的组织方式有哪些？",
                 "talk_emo": "tiwen", "listen_emo": "sikao"},
                {"type": "line", "speaker": "teacher", "text": "常见有顺序、索引和散列三种组织方式。",
                 "talk_emo": "yansu", "listen_emo": "gaoxing"},
                {"type": "question", "speaker": "teacher", "text": "下面哪个不是常见的文件组织方式？",
                 "talk_emo": "yansu", "listen_emo": "sikao",
                 "quiz_type": "choice", "choices": ["顺序", "索引", "散列", "链式"], "answer": 3,
                 "explain": "常见文件组织是顺序、索引、散列；链式更多用于空闲磁盘空间管理。"},
            ],
        },
        {
            "id": "ch_6",
            "title": "磁盘调度算法",
            "background": "走廊",
            "steps": [
                {"type": "line", "speaker": "teacher", "text": "磁盘读写的主要开销来自寻道，所以派生出各种调度算法。",
                 "talk_emo": "jiangjie", "listen_emo": "sikao"},
                {"type": "line", "speaker": "student", "text": "都有哪些常用的？",
                 "talk_emo": "tiwen", "listen_emo": "sikao"},
                {"type": "line", "speaker": "teacher", "text": "比如先来先服务 FCFS、最短寻道时间优先 SSTF、扫描算法 SCAN。",
                 "talk_emo": "jiangjie", "listen_emo": "gaoxing"},
                {"type": "question", "speaker": "teacher", "text": "请复述常用的磁盘调度算法。",
                 "talk_emo": "yansu", "listen_emo": "sikao",
                 "quiz_type": "short", "reference_points": ["FCFS", "SSTF", "SCAN"],
                 "explain": "常用：先来先服务FCFS、最短寻道时间优先SSTF、扫描算法SCAN。"},
            ],
        },
    ],
}

# —— 样例作答记录（有对有错，供报告/错题本演示）——
# 每行: (chapter_index, step_index, quiz_type, is_correct, question, your, correct, explain)
SAMPLE_ANALYTICS = [
    (0, 6, "choice", False, "下面哪个不是进程的基本状态？", "终止", "就绪、运行、阻塞、终止", 0),
    (1, 4, "fill", True, "线程切换比进程切换开销______。", "更小", "更小", 1),
    (2, 3, "short", False, "请说出死锁产生的必要条件。", "互斥、循环", "互斥、持有并等待、不可剥夺、循环等待", 2),
]
