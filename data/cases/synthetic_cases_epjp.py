# -*- coding: utf-8 -*-
"""Synthetic EP + JP cases (CASE-DEMO-081..096) for multi-jurisdiction coverage.

Everything here is fictitious: applicants, inventors, examiners and every
patent / publication number (reserved ranges: EP99000NN / JP20990000NN for the
applications, EP9990NNN / JP20999NNNNN / WO20999NNNNN for cited art — see
data/cases/README.md). Specs are built from per-topic facts by a template so
each case has a realistic section structure, several hundred characters of
description, and 7-12 claims with dependents.

Dates are stored as ROC tuples like the rest of synthetic_cases.py (the
renderers convert to the Western calendar / 令和 for EP / JP documents).
"""

from __future__ import annotations

# ────────────────────────────────────────────────────────────────────────────
# EP — English, EPO Communication pursuant to Article 94(3) EPC
# ────────────────────────────────────────────────────────────────────────────

_EP_TOPICS: list[dict] = [
    {
        "title": "Battery management system with adaptive cell balancing",
        "field": "battery management systems for lithium-ion traction batteries",
        "device": "battery management system",
        "elements": [
            "a plurality of cell monitoring units (12) each measuring a voltage and a temperature of a battery cell",
            "a balancing circuit (14) comprising a switchable bleed resistor for each cell",
            "a controller (16) configured to estimate a state of charge of each cell from the measured voltage",
            "wherein the controller activates the bleed resistor of a cell only when its state of charge exceeds the pack mean by more than an adaptive threshold that decreases with pack temperature",
        ],
        "features": [
            "the adaptive threshold is between 0.5 % and 3 % state of charge",
            "the controller suspends balancing when any cell temperature exceeds 45 °C",
            "the balancing circuit further comprises an inductive transfer stage (18) moving charge from the highest to the lowest cell",
            "the state of charge is estimated with an extended Kalman filter",
            "the cell monitoring units communicate with the controller over an isolated daisy-chain bus (20)",
        ],
        "method": "A method of balancing cells of a traction battery",
        "steps": [
            "measuring a voltage and a temperature of each cell",
            "estimating a state of charge of each cell",
            "activating a bleed resistor of a cell whose state of charge exceeds the pack mean by more than an adaptive threshold that decreases with pack temperature",
        ],
        "prior": [
            ("passive balancing with a fixed voltage threshold", "wastes energy at low temperature where cell voltages diverge transiently"),
            ("fully active inductive balancing", "adds cost and electromagnetic interference to every cell"),
        ],
        "effect": "reduces balancing losses by approximately 38 % and extends usable pack capacity by 4 % over 1,000 cycles",
        "embodiment": "In a 96-cell pack the controller (16) samples every cell at 10 Hz; at 25 °C the threshold is 2 %, falling linearly to 0.5 % at -10 °C.",
        "signs": "10: battery management system; 12: cell monitoring unit; 14: balancing circuit; 16: controller; 18: inductive transfer stage; 20: daisy-chain bus",
        "applicant": "Nordhavn Energy Systems GmbH",
        "inventors": ["Lena Vogt", "Mateo Ruiz", "Anika Brandt"],
    },
    {
        "title": "Wind turbine blade with de-icing heating mat",
        "field": "wind turbine rotor blades operating in cold climates",
        "device": "wind turbine blade",
        "elements": [
            "a blade shell (32) having a leading edge (34)",
            "a carbon-fibre heating mat (36) embedded in the shell along the leading edge",
            "an ice detection sensor (38) arranged in the blade root",
            "a power controller (40) configured to energise zones of the heating mat sequentially from tip to root in response to the ice detection sensor",
        ],
        "features": [
            "the heating mat is divided into at least four independently powered zones",
            "the zone nearest the tip receives a power density of at least 3 kW/m²",
            "the ice detection sensor is an accelerometer detecting a mass imbalance of the rotor",
            "the heating mat is covered by an erosion-resistant polyurethane layer (42)",
            "the power controller limits total heating power to 5 % of rated turbine power",
        ],
        "method": "A method of de-icing a wind turbine blade",
        "steps": [
            "detecting ice accretion by means of a sensor in the blade root",
            "energising zones of a heating mat embedded along the leading edge sequentially from tip to root",
            "de-energising each zone once its surface temperature exceeds a release temperature",
        ],
        "prior": [
            ("hot-air circulation inside the blade", "heats the whole cavity and is slow for thick carbon shells"),
            ("simultaneous heating of the entire leading edge", "requires peak power exceeding the auxiliary supply"),
        ],
        "effect": "restores 95 % of rated power within 40 minutes of an icing event while halving the peak heating power",
        "embodiment": "For a 72 m blade five zones of 12 m each are used; the controller (40) switches zones every 6 minutes.",
        "signs": "30: blade; 32: blade shell; 34: leading edge; 36: heating mat; 38: ice detection sensor; 40: power controller; 42: protective layer",
        "applicant": "Skarvik Wind A/S",
        "inventors": ["Jonas Holm", "Freja Lund"],
    },
    {
        "title": "Medical infusion pump with occlusion detection",
        "field": "volumetric infusion pumps for intravenous therapy",
        "device": "infusion pump",
        "elements": [
            "a peristaltic pumping mechanism (52) acting on an infusion line",
            "a force sensor (54) arranged downstream of the pumping mechanism",
            "a motor current sensor (56)",
            "a processor (58) configured to signal a downstream occlusion when a rate of change of the sensed force and a rise in motor current both exceed respective thresholds within a common time window",
        ],
        "features": [
            "the common time window is between 2 and 10 seconds",
            "the thresholds are scaled with the programmed flow rate",
            "the processor reverses the pumping mechanism by a bolus-reduction volume after signalling the occlusion",
            "the bolus-reduction volume is between 0.1 ml and 0.5 ml",
            "the pump comprises an upstream air-in-line detector (60)",
        ],
        "method": "A method of detecting a downstream occlusion in an infusion pump",
        "steps": [
            "sensing a force on the infusion line downstream of a pumping mechanism",
            "sensing a motor current of the pumping mechanism",
            "signalling an occlusion when both a force rate of change and a motor current rise exceed thresholds within a common time window",
        ],
        "prior": [
            ("a single absolute pressure threshold", "responds late at low flow rates such as 1 ml/h"),
            ("motor current monitoring alone", "produces false alarms when the line is bent temporarily"),
        ],
        "effect": "shortens time-to-alarm at 1 ml/h from about 40 minutes to under 8 minutes with fewer than one false alarm per 1,000 hours",
        "embodiment": "The processor (58) evaluates both signals every 100 ms; at 1 ml/h the force-rate threshold is 0.02 N/s.",
        "signs": "50: infusion pump; 52: pumping mechanism; 54: force sensor; 56: motor current sensor; 58: processor; 60: air-in-line detector",
        "applicant": "Calvera Medical S.r.l.",
        "inventors": ["Giulia Serra", "Marco Bellini", "Chiara Conti"],
    },
    {
        "title": "Heat pump with refrigerant leak mitigation",
        "field": "domestic heat pumps using flammable refrigerants such as R290",
        "device": "heat pump",
        "elements": [
            "a refrigerant circuit (72) containing a flammable refrigerant",
            "an outdoor unit (74) housing a compressor",
            "a gas sensor (76) arranged in an indoor hydraulic module",
            "shut-off valves (78) operable to isolate the refrigerant circuit inside the outdoor unit when the gas sensor detects refrigerant",
        ],
        "features": [
            "the shut-off valves are normally-closed solenoid valves",
            "the compressor performs a pump-down into the outdoor unit before the valves close",
            "the gas sensor is a non-dispersive infrared sensor",
            "a ventilation fan (80) of the hydraulic module is activated on detection",
            "the refrigerant charge is less than 150 g",
        ],
        "method": "A method of operating a heat pump with a flammable refrigerant",
        "steps": [
            "monitoring refrigerant concentration in an indoor hydraulic module",
            "pumping the refrigerant down into an outdoor unit on detection",
            "closing shut-off valves to isolate the refrigerant inside the outdoor unit",
        ],
        "prior": [
            ("placing the whole circuit outdoors", "requires a water circuit that can freeze"),
            ("limiting refrigerant charge only", "caps heating capacity for larger dwellings"),
        ],
        "effect": "keeps indoor refrigerant concentration below 20 % of the lower flammability limit in all tested leak scenarios",
        "embodiment": "Pump-down takes 45 s at 50 Hz compressor speed; the valves (78) close when suction pressure drops below 1.2 bar.",
        "signs": "70: heat pump; 72: refrigerant circuit; 74: outdoor unit; 76: gas sensor; 78: shut-off valves; 80: ventilation fan",
        "applicant": "Thermaris Klimatechnik AG",
        "inventors": ["Felix Aebi", "Nora Keller"],
    },
    {
        "title": "Autonomous warehouse robot with collision-free path replanning",
        "field": "mobile robots transporting goods in automated warehouses",
        "device": "warehouse robot",
        "elements": [
            "a drive unit (92) with differential wheels",
            "a lidar sensor (94) providing a two-dimensional scan",
            "a communication module (96) receiving reservations of grid cells from a fleet server",
            "a planner (98) configured to replan a path locally only through grid cells reserved for the robot when the lidar sensor detects an obstacle not present in a shared map",
        ],
        "features": [
            "the reservation covers a time window of at most 5 seconds ahead",
            "the planner uses a time-expanded A* search",
            "the robot requests additional grid cells when no path exists within its reservation",
            "the lidar sensor is mounted at a height of 15 cm to 25 cm",
            "the robot reduces speed to 0.3 m/s when replanning",
        ],
        "method": "A method of navigating a warehouse robot",
        "steps": [
            "receiving a reservation of grid cells from a fleet server",
            "detecting an obstacle not present in a shared map",
            "replanning a path locally only through reserved grid cells",
        ],
        "prior": [
            ("central replanning by the fleet server", "introduces latency exceeding one second for large fleets"),
            ("purely local obstacle avoidance", "causes deadlocks between neighbouring robots"),
        ],
        "effect": "reduces deadlocks by 90 % and keeps replanning latency below 50 ms for fleets of 500 robots",
        "embodiment": "The grid has 0.5 m cells; the planner (98) runs at 20 Hz on an embedded processor.",
        "signs": "90: robot; 92: drive unit; 94: lidar sensor; 96: communication module; 98: planner",
        "applicant": "Brückner Logistics Robotics GmbH",
        "inventors": ["Tobias Wendt", "Sara Nilsson"],
    },
    {
        "title": "Coated cutting insert with multilayer aluminium oxide coating",
        "field": "coated cemented carbide inserts for metal turning",
        "device": "cutting insert",
        "elements": [
            "a cemented carbide substrate (112)",
            "a titanium carbonitride inner layer (114) with a thickness of 4 µm to 10 µm",
            "an alpha-alumina outer layer (116) with a thickness of 3 µm to 8 µm",
            "wherein the alpha-alumina layer exhibits a texture coefficient TC(0 0 12) of at least 6",
        ],
        "features": [
            "the texture coefficient TC(0 0 12) is at least 7",
            "a bonding layer (118) of titanium oxycarbonitride is arranged between the inner and outer layers",
            "the outer layer is subjected to wet blasting to a residual compressive stress of at least 1 GPa",
            "the substrate contains 5 wt % to 7 wt % cobalt",
            "a titanium nitride top layer is removed from the rake face",
        ],
        "method": "A method of producing a coated cutting insert",
        "steps": [
            "depositing a titanium carbonitride layer by MT-CVD at 850 °C to 900 °C",
            "depositing an alpha-alumina layer by CVD at 1000 °C with a controlled CO2 ratio",
            "wet blasting the coated insert",
        ],
        "prior": [
            ("alumina coatings with random texture", "suffer crater wear at high cutting speeds"),
            ("(0 0 1)-textured coatings with thin inner layers", "show flaking in interrupted cuts"),
        ],
        "effect": "increases tool life in turning of 42CrMo4 at 300 m/min by approximately 45 %",
        "embodiment": "Example 1 uses a 7 µm Ti(C,N) layer and a 5 µm alumina layer with TC(0 0 12) = 7.4 measured by XRD.",
        "signs": "110: insert; 112: substrate; 114: inner layer; 116: outer layer; 118: bonding layer",
        "applicant": "Uppland Hårdmetall AB",
        "inventors": ["Erik Sjöberg", "Maja Lindqvist"],
    },
    {
        "title": "Method for training a neural network for defect detection with synthetic images",
        "field": "machine-vision inspection of printed circuit boards",
        "device": "inspection system",
        "elements": [
            "a camera (132) capturing images of printed circuit boards",
            "a generator (134) producing synthetic defect images by inserting rendered defects into defect-free images",
            "a neural network (136) trained on real and synthetic images",
            "wherein the generator adjusts rendered defect geometry so that a discriminator cannot distinguish synthetic from real defect patches",
        ],
        "features": [
            "the defects comprise solder bridges, missing components and tombstoning",
            "the ratio of synthetic to real training images is between 1:1 and 5:1",
            "the neural network is a convolutional network with a feature pyramid",
            "the system flags boards whose defect probability exceeds 0.8 for manual review",
            "the camera captures images under three illumination angles",
        ],
        "method": "A computer-implemented method of training a neural network for defect detection",
        "steps": [
            "rendering defects into defect-free images of printed circuit boards",
            "adjusting rendered defect geometry until a discriminator cannot distinguish synthetic from real defect patches",
            "training the neural network on real and synthetic images",
        ],
        "prior": [
            ("training on real defect images only", "lacks examples of rare defect classes"),
            ("simple copy-paste augmentation", "produces visible seams that the network learns as a shortcut"),
        ],
        "effect": "raises recall on rare defect classes from 71 % to 93 % at unchanged false-call rate",
        "embodiment": "The generator (134) renders 20,000 synthetic images per defect class; training uses 8 GPUs for 12 hours.",
        "signs": "130: inspection system; 132: camera; 134: generator; 136: neural network",
        "applicant": "Veltris Vision B.V.",
        "inventors": ["Daan Visser", "Iris de Groot"],
    },
    {
        "title": "Food packaging tray with compostable barrier layer",
        "field": "packaging trays for chilled fresh food",
        "device": "packaging tray",
        "elements": [
            "a moulded fibre body (152)",
            "a barrier layer (154) of polybutylene succinate laminated to an inner surface of the body",
            "a sealing flange (156) extending around an opening of the body",
            "wherein the barrier layer has a thickness of 15 µm to 40 µm and an oxygen transmission rate below 50 cm³/(m²·day·bar)",
        ],
        "features": [
            "the barrier layer further comprises a polyvinyl alcohol core",
            "the moulded fibre body comprises bagasse fibres",
            "the sealing flange has a width of 4 mm to 8 mm",
            "the tray is certified industrially compostable according to EN 13432",
            "the body has a basis weight of 400 g/m² to 700 g/m²",
        ],
        "method": "A method of manufacturing a packaging tray",
        "steps": [
            "thermoforming a moulded fibre body",
            "laminating a polybutylene succinate barrier film to the inner surface under heat and vacuum",
            "trimming a sealing flange around the opening",
        ],
        "prior": [
            ("fibre trays with polyethylene liners", "are not compostable and hard to recycle"),
            ("uncoated fibre trays", "absorb moisture and lose stiffness within hours"),
        ],
        "effect": "provides a shelf life for sliced meat of 10 days while remaining compostable",
        "embodiment": "A 25 µm three-layer PBS/PVOH/PBS film is laminated at 140 °C; the resulting tray withstands 1 kg top load after 7 days at 4 °C.",
        "signs": "150: tray; 152: body; 154: barrier layer; 156: sealing flange",
        "applicant": "Ostrava Pack s.r.o.",
        "inventors": ["Petra Novak", "Jan Dvořák"],
    },
]

_EP_REJECTIONS = [
    # (statute, rejection_type, affected, n_cited, argument template)
    ("Article 56 EPC", "103_obviousness", [1, 2, 3], 2,
     "Document D1 ({c0}) is regarded as the closest prior art and discloses a {device} with all features of claim 1 except the last feature. "
     "The objective technical problem is to improve efficiency under varying operating conditions. D2 ({c1}) addresses the same problem and "
     "teaches the missing feature; the skilled person would combine D1 with D2 without inventive skill. Claims 2 and 3 add routine design choices."),
    ("Article 54(1),(2) EPC", "102_novelty", [1], 1,
     "Document D1 ({c0}) discloses, in its second embodiment and Fig. 3, a {device} having every feature of claim 1, "
     "including the characterising feature. The subject-matter of claim 1 is therefore not new."),
    ("Article 84 EPC", "112_indefiniteness", [4], 0,
     "In claim 4 the feature \"{f4}\" refers to a parameter without stating how or under which conditions it is measured, "
     "so that the skilled person cannot establish whether a given product falls within the claim. "
     "The scope of protection is therefore not clearly defined."),
    ("Article 123(2) EPC", "other", [5], 0,
     "The amendment introducing the numerical range in claim 5 is not directly and unambiguously derivable from the application as filed, "
     "which discloses only a single example value. The amendment adds subject-matter extending beyond the content of the application as filed."),
]

# ────────────────────────────────────────────────────────────────────────────
# JP — Japanese, 拒絶理由通知書
# ────────────────────────────────────────────────────────────────────────────

_JP_TOPICS: list[dict] = [
    {
        "title": "半導体ウェハの洗浄装置",
        "field": "半導体製造工程におけるウェハの枚葉式洗浄装置",
        "device": "洗浄装置",
        "elements": [
            "ウェハ（W）を保持して回転させるスピンチャック（12）と",
            "前記ウェハの表面に二流体ミストを噴射するノズル（14）と",
            "前記ノズルを前記ウェハの半径方向に走査させるアーム（16）と",
            "前記ノズルの走査速度を前記ウェハの中心からの距離に反比例するように制御する制御部（18）と",
        ],
        "features": [
            "前記二流体ミストの液滴径は5μm以上20μm以下である",
            "前記制御部は、前記ウェハの回転数を300rpm以上1500rpm以下に制御する",
            "前記ノズルの噴射角度は前記ウェハ表面に対して30度以上60度以下である",
            "前記洗浄液は炭酸ガスを溶解させた純水である",
            "前記アームの先端に前記ウェハとの距離を測定する距離センサ（20）を備える",
        ],
        "method": "ウェハの洗浄方法",
        "steps": [
            "ウェハを回転させる工程と",
            "二流体ミストを噴射するノズルを前記ウェハの半径方向に走査させる工程と",
            "前記ノズルの走査速度を前記ウェハの中心からの距離に反比例させる工程と",
        ],
        "prior": [
            ("一定速度でノズルを走査する方式", "ウェハ外周部で単位面積当たりの洗浄時間が不足する"),
            ("高圧ジェットによる洗浄", "微細パターンの倒壊を招く"),
        ],
        "effect": "直径30nm以上のパーティクル除去率を92%から99.2%に向上させ、パターン倒壊を発生させない",
        "embodiment": "直径300mmのウェハに対し、制御部（18）は中心から10mmの位置で走査速度を50mm/秒とし、外周で3.3mm/秒まで低下させる。",
        "signs": "10：洗浄装置、12：スピンチャック、14：ノズル、16：アーム、18：制御部、20：距離センサ",
        "applicant": "東雲精機株式会社",
        "inventors": ["高橋 悠真", "佐々木 美咲"],
    },
    {
        "title": "車両用ヘッドアップディスプレイ装置",
        "field": "車両のウインドシールドに虚像を投影するヘッドアップディスプレイ",
        "device": "ヘッドアップディスプレイ装置",
        "elements": [
            "画像光を出射する表示器（32）と",
            "前記画像光を反射する凹面鏡（34）と",
            "運転者の目の位置を検出するカメラ（36）と",
            "前記目の位置に応じて前記凹面鏡の角度を調整するとともに前記画像の歪み補正量を切り替える制御部（38）と",
        ],
        "features": [
            "前記歪み補正量は、前記目の位置ごとに予め記憶された補正テーブルから選択される",
            "前記凹面鏡はステッピングモータ（40）により回動される",
            "前記表示器はレーザ走査型である",
            "前記制御部は車速が所定値以上のとき前記凹面鏡の調整を禁止する",
            "前記虚像の結像距離は7m以上である",
        ],
        "method": "ヘッドアップディスプレイの表示制御方法",
        "steps": [
            "運転者の目の位置を検出する工程と",
            "前記目の位置に応じて凹面鏡の角度を調整する工程と",
            "前記目の位置に応じて画像の歪み補正量を切り替える工程と",
        ],
        "prior": [
            ("手動で凹面鏡の角度を調整する方式", "姿勢変化に追従できず虚像が見切れる"),
            ("単一の歪み補正テーブルを用いる方式", "目の位置が変わると虚像が歪んで見える"),
        ],
        "effect": "アイボックス全域で虚像の歪みを0.5%以下に抑え、見切れの発生をなくす",
        "embodiment": "カメラ（36）は赤外LEDを用いて毎秒60フレームで目の位置を検出し、制御部（38）は12個の補正テーブルを切り替える。",
        "signs": "30：ヘッドアップディスプレイ装置、32：表示器、34：凹面鏡、36：カメラ、38：制御部、40：ステッピングモータ",
        "applicant": "朝凪電装株式会社",
        "inventors": ["中村 翔太", "小林 由衣"],
    },
    {
        "title": "全固体電池用硫化物固体電解質",
        "field": "全固体リチウムイオン電池に用いる硫化物系固体電解質",
        "device": "硫化物固体電解質",
        "elements": [
            "Li、P、S及びハロゲン元素を含み",
            "アルジロダイト型結晶構造を有し",
            "CuKα線を用いたX線回折測定において2θ=25.2°±0.5°及び29.7°±0.5°にピークを有し",
            "前記ハロゲン元素に対するLiのモル比が5.0以上6.0以下である",
        ],
        "features": [
            "前記ハロゲン元素は塩素及び臭素を含む",
            "25℃におけるイオン伝導度が5mS/cm以上である",
            "平均粒径D50が0.5μm以上3μm以下である",
            "露点-40℃の雰囲気に1時間暴露した後の硫化水素発生量が1cm³/g以下である",
            "酸素を0.1質量%以上1質量%以下含む",
        ],
        "method": "硫化物固体電解質の製造方法",
        "steps": [
            "Li2S、P2S5及びハロゲン化リチウムを混合する工程と",
            "得られた混合物を遊星ボールミルで粉砕する工程と",
            "粉砕物を400℃以上500℃以下で焼成する工程と",
        ],
        "prior": [
            ("ハロゲンを含まない硫化物電解質", "イオン伝導度が1mS/cm程度にとどまる"),
            ("塩素のみを含むアルジロダイト", "大気中の水分と反応して硫化水素が発生しやすい"),
        ],
        "effect": "イオン伝導度7.2mS/cmと大気安定性とを両立する",
        "embodiment": "実施例1では、Li2S、P2S5、LiCl及びLiBrをモル比5:1:1:1で混合し、450℃で8時間焼成した。",
        "signs": "（図面なし）",
        "applicant": "蒼嶺マテリアル株式会社",
        "inventors": ["松本 健太", "井上 彩花", "木村 大輔"],
    },
    {
        "title": "農業用ドローンの薬剤散布制御システム",
        "field": "無人航空機による圃場への農薬散布",
        "device": "散布制御システム",
        "elements": [
            "機体に搭載された散布ノズル（52）と",
            "圃場の作物の生育状態を示す指標マップを記憶する記憶部（54）と",
            "前記機体の位置を測位するGNSS受信機（56）と",
            "前記指標マップと前記機体の位置とに基づいて前記散布ノズルからの吐出量を区画ごとに変化させる制御部（58）と",
        ],
        "features": [
            "前記指標マップは正規化植生指数（NDVI）に基づいて作成される",
            "前記区画の大きさは1m四方以上5m四方以下である",
            "前記制御部は風速計（60）の出力に応じて吐出量を補正する",
            "前記GNSS受信機はRTK測位を行う",
            "前記制御部は散布履歴を前記記憶部に記録する",
        ],
        "method": "ドローンによる薬剤散布方法",
        "steps": [
            "圃場の指標マップを取得する工程と",
            "機体の位置を測位する工程と",
            "前記指標マップと前記位置とに基づいて吐出量を区画ごとに変化させる工程と",
        ],
        "prior": [
            ("圃場全体に一定量を散布する方式", "薬剤使用量が過大となる"),
            ("手動で散布量を切り替える方式", "操縦者の負担が大きく精度が低い"),
        ],
        "effect": "薬剤使用量を約30%削減しつつ、病害発生率を従来と同等以下に維持する",
        "embodiment": "制御部（58）は10Hzで位置を取得し、2m四方の区画ごとに吐出量を0.5L/分から1.5L/分の範囲で調整する。",
        "signs": "50：散布制御システム、52：散布ノズル、54：記憶部、56：GNSS受信機、58：制御部、60：風速計",
        "applicant": "穂波アグリテック株式会社",
        "inventors": ["山口 拓海", "森 さくら"],
    },
    {
        "title": "情報処理装置、情報処理方法及びプログラム",
        "field": "店舗における在庫補充作業の支援",
        "device": "情報処理装置",
        "elements": [
            "商品棚を撮影した画像から欠品領域を検出する検出部（72）と",
            "販売実績データに基づいて商品ごとの欠品による機会損失額を推定する推定部（74）と",
            "前記機会損失額の大きい順に補充作業の優先順位を決定する決定部（76）と",
            "前記優先順位を作業者の端末に通知する通知部（78）と",
        ],
        "features": [
            "前記検出部は、学習済みモデルを用いて前記欠品領域を検出する",
            "前記推定部は、時間帯ごとの販売実績に基づいて前記機会損失額を推定する",
            "前記決定部は、作業者の現在位置からの移動距離を考慮して前記優先順位を補正する",
            "前記通知部は、補充すべき商品の在庫保管場所を併せて通知する",
            "前記画像は店舗の天井に設置されたカメラ（80）により撮影される",
        ],
        "method": "情報処理方法",
        "steps": [
            "商品棚の画像から欠品領域を検出するステップと",
            "商品ごとの欠品による機会損失額を推定するステップと",
            "前記機会損失額に基づいて補充作業の優先順位を決定して通知するステップと",
        ],
        "prior": [
            ("定時巡回による目視確認", "欠品の発見が遅れ機会損失が大きい"),
            ("欠品検出のみを行うシステム", "補充の優先度が考慮されず作業効率が低い"),
        ],
        "effect": "欠品による機会損失額を約25%削減する",
        "embodiment": "検出部（72）は5分ごとに画像を取得し、推定部（74）は直近4週間の同時間帯の販売実績を用いる。",
        "signs": "70：情報処理装置、72：検出部、74：推定部、76：決定部、78：通知部、80：カメラ",
        "applicant": "株式会社ミナトリテールラボ",
        "inventors": ["加藤 陸", "吉田 真央"],
    },
    {
        "title": "内視鏡用処置具",
        "field": "内視鏡を介して体腔内で使用される把持鉗子",
        "device": "内視鏡用処置具",
        "elements": [
            "可撓性シース（92）と",
            "前記シースの先端に設けられ開閉する一対の把持片（94）と",
            "前記シース内に挿通され前記把持片を開閉させる操作ワイヤ（96）と",
            "前記把持片の把持面に設けられ把持力を検出する圧力センサ（98）と",
        ],
        "features": [
            "前記圧力センサは薄膜圧電素子である",
            "前記把持力が閾値を超えたときに操作部に振動を発生させる振動子（100）を備える",
            "前記閾値は0.5N以上2N以下である",
            "前記把持片は前記シースに対して回転可能である",
            "前記把持面には高さ0.2mm以下の凹凸が形成されている",
        ],
        "method": "（方法クレームなし）",
        "steps": [],
        "prior": [
            ("力覚フィードバックのない把持鉗子", "組織を過度に把持して損傷させるおそれがある"),
            ("操作部側で張力を測定する方式", "シースの摩擦により把持力を正確に推定できない"),
        ],
        "effect": "組織損傷の発生率を約60%低減する",
        "embodiment": "圧力センサ（98）は把持片（94）の先端から2mmの位置に配置され、0.1N単位で把持力を検出する。",
        "signs": "90：内視鏡用処置具、92：シース、94：把持片、96：操作ワイヤ、98：圧力センサ、100：振動子",
        "applicant": "白鷺メディカル株式会社",
        "inventors": ["林 優斗", "清水 花"],
    },
    {
        "title": "コンクリート構造物のひび割れ補修材",
        "field": "コンクリート構造物のひび割れを自己治癒させる補修材",
        "device": "ひび割れ補修材",
        "elements": [
            "ポリマーセメントモルタルと",
            "前記モルタル100質量部に対して0.5質量部以上3質量部以下のバチルス属細菌の芽胞と",
            "乳酸カルシウムからなる栄養源と",
            "前記芽胞及び前記栄養源を内包する平均粒径50μm以上300μm以下のカプセル（112）と",
        ],
        "features": [
            "前記カプセルはアルギン酸カルシウムからなる",
            "前記栄養源の含有量は前記モルタル100質量部に対して2質量部以上6質量部以下である",
            "幅0.3mmのひび割れを28日以内に閉塞させる",
            "前記ポリマーセメントモルタルはアクリル系ポリマーを含む",
            "前記補修材は吹付け施工用である",
        ],
        "method": "コンクリート構造物の補修方法",
        "steps": [
            "ひび割れ部を清掃する工程と",
            "芽胞及び栄養源を内包したカプセルを含む補修材を塗布する工程と",
            "前記補修材を湿潤養生する工程と",
        ],
        "prior": [
            ("エポキシ樹脂の注入", "再発したひび割れに対応できない"),
            ("細菌を直接混合する方式", "練混ぜ時に細菌が死滅しやすい"),
        ],
        "effect": "再発したひび割れを自己治癒させ、透水量を初期値の5%以下に回復させる",
        "embodiment": "実施例では平均粒径150μmのカプセル（112）を1.5質量部配合し、20℃湿潤養生で幅0.3mmのひび割れが21日で閉塞した。",
        "signs": "110：補修材、112：カプセル",
        "applicant": "潮見建材工業株式会社",
        "inventors": ["斎藤 蓮", "山本 結衣"],
    },
    {
        "title": "音声認識装置",
        "field": "雑音環境下での音声認識",
        "device": "音声認識装置",
        "elements": [
            "複数のマイクロホン（132）と",
            "前記マイクロホンの出力から話者方向を推定する方向推定部（134）と",
            "推定された話者方向に指向性を形成するビームフォーマ（136）と",
            "前記ビームフォーマの出力に対して音声認識を行う認識部（138）とを備え、前記方向推定部は前記認識部の認識信頼度が閾値を下回ったときに話者方向を再推定する",
        ],
        "features": [
            "前記マイクロホンは円形に配置された6個である",
            "前記ビームフォーマは最小分散無歪応答（MVDR）ビームフォーマである",
            "前記閾値は0.6である",
            "前記認識部はエンドツーエンド型のニューラルネットワークを用いる",
            "前記方向推定部は、前記再推定の際に探索範囲を前回推定方向の±30度に限定する",
        ],
        "method": "音声認識方法",
        "steps": [
            "複数のマイクロホンの出力から話者方向を推定するステップと",
            "話者方向に指向性を形成するステップと",
            "認識信頼度が閾値を下回ったときに話者方向を再推定するステップと",
        ],
        "prior": [
            ("固定方向のビームフォーミング", "話者が移動すると認識率が低下する"),
            ("常時方向推定を行う方式", "演算量が大きく組込み機器に適さない"),
        ],
        "effect": "SN比0dBの環境で単語誤り率を28%から14%に低減し、演算量を約40%削減する",
        "embodiment": "マイクロホン（132）は半径4cmの円周上に配置され、方向推定部（134）はGCC-PHAT法を用いる。",
        "signs": "130：音声認識装置、132：マイクロホン、134：方向推定部、136：ビームフォーマ、138：認識部",
        "applicant": "株式会社カナリア音響研究所",
        "inventors": ["岡田 颯", "藤田 七海"],
    },
]

_JP_REJECTIONS = [
    ("特許法第29条第2項", "103_obviousness", [1, 2, 3], 2,
     "引用文献1（{c0}）には、{device}であって、請求項1の最後の構成を除く全ての構成を備えたものが記載されている。"
     "引用文献2（{c1}）には、同様の課題を解決するために当該構成を採用することが記載されており、"
     "引用文献1に記載された発明に引用文献2に記載された技術を適用することは、当業者が容易に想到し得たことである。"
     "請求項2及び3に係る発明についても、設計的事項にすぎない。"),
    ("特許法第29条第1項第3号", "102_novelty", [1], 1,
     "引用文献1（{c0}）の段落【0025】～【0031】及び図3には、請求項1に係る発明の全ての構成が記載されている。"
     "したがって、請求項1に係る発明は、引用文献1に記載された発明である。"),
    ("特許法第36条第6項第2号", "112_indefiniteness", [4], 0,
     "請求項4の「{f4}」との記載は、その測定条件又は技術的意味が請求項の記載からも発明の詳細な説明からも特定できず、"
     "特許を受けようとする発明が明確でない。"),
    ("特許法第36条第6項第1号", "other", [5], 0,
     "請求項5に記載された数値範囲の全体にわたって発明の課題が解決できることが、発明の詳細な説明に記載された"
     "単一の実施例からは当業者が認識できず、請求項5に係る発明は発明の詳細な説明に記載したものではない。"),
]

_EP_EXAMINERS = ["K. Hoffmann", "A. Moreau", "P. Lindgren", "S. Rossi"]
_JP_EXAMINERS = ["山田 一郎", "鈴木 花子", "田中 誠", "渡辺 恵"]
_EP_DIVISIONS = ["Munich", "The Hague", "Berlin"]
_EP_IPC = ["H01M 10/42", "F03D 80/40", "A61M 5/168", "F25B 49/02", "G05D 1/02", "C23C 16/40", "G06T 7/00", "B65D 65/46"]
_JP_IPC = ["H01L 21/304", "G02B 27/01", "H01M 10/0562", "A01M 7/00", "G06Q 10/087", "A61B 17/29", "C04B 28/02", "G10L 15/20"]


def _ep_spec(t: dict) -> str:
    (p1, d1), (p2, d2) = t["prior"]
    return (
        "Technical field\n"
        f"The present invention relates to {t['field']}, and in particular to a {t['device']} and a corresponding method.\n\n"
        "Background art\n"
        f"A first known approach uses {p1}; however, it {d1}. A second known approach relies on {p2}, which {d2}. "
        "Neither approach provides reliable operation over the full range of operating conditions at acceptable cost.\n\n"
        "Summary of the invention\n"
        f"It is an object of the invention to provide a {t['device']} overcoming these drawbacks. The object is achieved by a "
        f"{t['device']} comprising " + "; ".join(t["elements"]) + ". "
        f"Compared with the prior art, the invention {t['effect']}.\n\n"
        "Brief description of the drawings\n"
        f"Fig. 1 shows a schematic view of a {t['device']} according to a first embodiment. Fig. 2 shows a flow chart of the method. "
        "Fig. 3 shows measurement results comparing the embodiment with the prior art.\n\n"
        "Detailed description of embodiments\n"
        f"{t['embodiment']} In a variant, " + "; in a further variant, ".join(t["features"][:3]) + ". "
        "The features of the embodiments may be combined unless they are technically incompatible.\n\n"
        f"Reference signs\n{t['signs']}\n"
    )


def _jp_spec(t: dict) -> str:
    (p1, d1), (p2, d2) = t["prior"]
    return (
        "【技術分野】\n"
        f"本発明は、{t['field']}に関し、特に{t['device']}に関する。\n\n"
        "【背景技術】\n"
        f"従来、{p1}が知られているが、{d1}という問題がある。また、{p2}も提案されているが、{d2}。\n\n"
        "【発明が解決しようとする課題】\n"
        f"本発明は、上記事情に鑑みてなされたものであり、従来技術の問題を解消する{t['device']}を提供することを目的とする。\n\n"
        "【課題を解決するための手段】\n"
        f"本発明の{t['device']}は、" + "、".join(e.rstrip("と") for e in t["elements"]) + "ことを特徴とする。\n\n"
        "【発明の効果】\n"
        f"本発明によれば、{t['effect']}。\n\n"
        "【発明を実施するための形態】\n"
        f"{t['embodiment']}変形例として、" + "。他の変形例として、".join(t["features"][:3]) + "。"
        "各実施形態の構成は、技術的に矛盾しない範囲で適宜組み合わせることができる。\n\n"
        f"【符号の説明】\n{t['signs']}\n"
    )


def _ep_claims(t: dict) -> list[str]:
    claims = [f"A {t['device']} comprising: " + "; ".join(t["elements"]) + "."]
    for f in t["features"][:-1]:
        claims.append(f"The {t['device']} according to claim 1, wherein {f}.")
    # one dependent-on-dependent claim
    claims.append(f"The {t['device']} according to claim 2 or 3, wherein {t['features'][-1]}.")
    if t["steps"]:
        n = len(claims) + 1
        claims.append(f"{t['method']}, comprising: " + "; ".join(t["steps"]) + ".")
        claims.append(f"The method according to claim {n}, wherein {t['features'][0]}.")
    return claims


def _jp_claims(t: dict) -> list[str]:
    els = t["elements"]
    if all(e.endswith("と") for e in els):  # 「Aと、Bと、Cとを備える」
        first = "、".join(els) + f"を備える{t['device']}。"
    else:  # 組成物「…を含み、…を有し、…である」/「…とを備え、前記…は…する」
        first = "、".join(els) + f"{t['device']}。"
    claims = [first]
    for f in t["features"][:-1]:
        claims.append(f"{f}、請求項1に記載の{t['device']}。")
    claims.append(f"{t['features'][-1]}、請求項2又は3に記載の{t['device']}。")
    if t["steps"]:
        claims.append("、".join(t["steps"]) + f"を含む{t['method']}。")
    return claims


def _pick_rejections(table: list, idx: int, cited_pool: list[str], device: str, features: list[str]) -> list[dict]:
    # Rotate so each case gets 1-2 rejections; every type appears across the set.
    chosen = [table[idx % len(table)]]
    if idx % 2 == 0:
        chosen.append(table[(idx + 2) % len(table)])
    out, ci = [], 0
    for statute, rtype, affected, n_cited, tmpl in chosen:
        cited = cited_pool[ci : ci + n_cited]
        ci += n_cited
        fmt = {"device": device, "f4": features[2], "c0": cited[0] if cited else "", "c1": cited[1] if len(cited) > 1 else ""}
        out.append({
            "statute": statute,
            "rejection_type": rtype,
            "affected_claims": list(affected),
            "cited_prior_art": cited,
            "argument": tmpl.format(**fmt),
        })
    return out


def build_cases(start_index: int = 81) -> list[dict]:
    cases: list[dict] = []
    n = start_index
    for i, t in enumerate(_EP_TOPICS):
        claims = _ep_claims(t)
        pool = [f"EP9990{i * 3 + k + 1:03d}" for k in range(2)] + [f"WO2099900{i + 1:03d}"]
        cases.append({
            "case_id": f"CASE-DEMO-{n:03d}",
            "patent": {
                "patent_no": f"EP99000{i + 1:02d}",
                "title": t["title"],
                "abstract": f"A {t['device']} comprising " + "; ".join(t["elements"][:2]) + f"; the invention {t['effect']}.",
                "claims": claims,
                "spec_text": _ep_spec(t),
                "filing_date_roc": (112, 3 + i, 10 + i),
                "publication_date_roc": (113, 9, 4 + i),
                "ipc": [_EP_IPC[i]],
                "applicants": [t["applicant"]],
                "inventors": t["inventors"],
                "jurisdiction": "EP",
            },
            "oa": {
                "doc_type": "Communication pursuant to Article 94(3) EPC",
                "date_roc": (114, 2 + i, 6 + i),
                "doc_no": f"EPC94-{2025}-{i + 1:04d}",
                "examiner": _EP_EXAMINERS[i % len(_EP_EXAMINERS)],
                "division": _EP_DIVISIONS[i % len(_EP_DIVISIONS)],
                "response_months": 4,
                "rejections": _pick_rejections(_EP_REJECTIONS, i, pool, t["device"], t["features"]),
            },
            "reexam": None,
        })
        n += 1
    for i, t in enumerate(_JP_TOPICS):
        claims = _jp_claims(t)
        pool = [f"JP20999{i * 3 + k + 1:05d}" for k in range(2)]
        cases.append({
            "case_id": f"CASE-DEMO-{n:03d}",
            "patent": {
                "patent_no": f"JP20990000{i + 1:02d}",
                "title": t["title"],
                "abstract": f"【課題】{t['field']}において従来技術の問題を解消する。【解決手段】" + "、".join(e.rstrip("と") for e in t["elements"][:2]) + f"。【効果】{t['effect']}。",
                "claims": claims,
                "spec_text": _jp_spec(t),
                "filing_date_roc": (112, 2 + i, 3 + i),
                "publication_date_roc": (113, 8, 20 + i),
                "ipc": [_JP_IPC[i]],
                "applicants": [t["applicant"]],
                "inventors": t["inventors"],
                "jurisdiction": "JP",
            },
            "oa": {
                "doc_type": "拒絶理由通知書",
                "date_roc": (114, 3 + i, 4 + i),
                "doc_no": f"JPOA-2025-{i + 1:04d}",
                "examiner": _JP_EXAMINERS[i % len(_JP_EXAMINERS)],
                # 国内出願人: 60日 (response_days). response_months kept for the
                # eval harness, which accepts +60 days as well.
                "response_months": 2,
                "response_days": 60,
                "rejections": _pick_rejections(_JP_REJECTIONS, i, pool, t["device"], t["features"]),
            },
            "reexam": None,
        })
        n += 1
    return cases
