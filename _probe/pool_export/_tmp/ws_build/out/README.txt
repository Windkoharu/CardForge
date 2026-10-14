CardForge 2.0 导出包 —— CardForge
生成时间：2026-10-13T06:24:55

════════════════════════════════════════════════════════════════════
一、怎么装
════════════════════════════════════════════════════════════════════
1) 把本目录 expansions/ 里的**全部内容**复制进 EDOPro 的 expansions/ 目录：

     Windows : %LOCALAPPDATA%\EDOPro\expansions
     macOS   : ~/Library/Application Support/EDOPro/expansions
     Linux   : ~/.local/share/EDOPro/expansions

   也可以交给工具自动做（复制前会自动备份同名文件）：

     cardforge export --install
     # 或 python -c "from cardforge.export import install; print(install.install(r'D:\游戏王DIY设计\_probe\pool_export\_tmp\ws_build\out'))"

2) 如果本包带 strings.conf，请把里面的 !setname / !counter 行**追加**到
   EDOPro 的 config/strings.conf（或放在 expansions/strings.conf，两种位置都认）。
   不做这一步，DIY 系列的「字段名」与「计数器名」在游戏里会显示成空白。

3) 重启 EDOPro。卡图放 expansions/pics/<卡号>.jpg，脚本放 expansions/script/c<卡号>.lua。

════════════════════════════════════════════════════════════════════
二、这个包里有什么
════════════════════════════════════════════════════════════════════
  卡数        ：5
  卡池文件    ：CardForge.cdb, CardForge-zh-CN.cdb, CardForge-ja.cdb
  语言        ：zh_cn, ja
  卡图        ：2 张；待补 3 张：210000002, 210000003, 210000004
  场地背景    ：1 张
  卡脚本      ：3 个
  系列名/计数器：已生成 strings.conf

  跳过项（前 20 条）：
    - [pic] 210000002 卡图不存在
    - [pic] 210000003 卡图不存在
    - [pic] 210000004 卡图不存在
    - [script] 210000002 spec.lua 为空
════════════════════════════════════════════════════════════════════
三、素材与字体许可（合规红线，务必读完）
════════════════════════════════════════════════════════════════════
1) 卡框素材的归属是模糊的。所有已知的 PSD/矢量卡框模板（DeviantArt、cardmaker.net
   论坛、百度贴吧）都没有明确的开源许可，卡框本身是 Konami 的美术设计。本项目采用的
   kooriookami/yugioh-card 是唯一带明确 MIT 声明的来源，署名义务由
   data/assets/NOTICE.txt 承担 —— 分发本包时请一并保留该声明。

2) 官方字体全部是商业字体（Matrix / Matrixed / ITC Stone Serif / DF 隷書体 /
   FOT-Rodin / HanWang LiSu / DF Kai W5）。社区流传的「游戏王字体包」属于二次分发，
   法律风险高，本项目不分发。

3) 因此本项目用三层素材策略：A 内置 MIT 素材 / B 系统 CJK 字体回退 / C OFL 开源字体
   （Cinzel、EB Garamond、Noto Serif SC·TC、霞鹜文楷 LXGW WenKai、Noto Serif KR）。

   ⚠ 本包内的卡面是按 A 或 B 层渲染的。**用于商业发行前必须换成 C 层字体与自绘素材。**
   个人 DIY、学习、非商业分享可以按原样使用。

════════════════════════════════════════════════════════════════════
四、问与答
════════════════════════════════════════════════════════════════════
Q: 卡在游戏里看不到？
A: 卡号必须 >= 210000000（避开官方池），且 cdb 必须放在 expansions/ 下、文件名以
   .cdb 结尾。用 cardforge.export.expansions.verify() 跑一遍会告诉你缺什么。

Q: 卡名/卡文是空白的？
A: 该 .cdb 的 texts 表缺行。基础包 <name>.cdb 一定带文本，语言包 <name>-xx.cdb 覆盖它。

Q: 效果不生效？
A: script/c<卡号>.lua 缺失，或 .lua 带了 UTF-8 BOM（BOM 会让 Lua 直接报错）。
   本包内所有 .lua 都已经过无 BOM 校验。
