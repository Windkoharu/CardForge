--[==[ 乱码/\:*?
     CardForge 2.0 生成 · 卡种=仪式（frame=ritual） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
     ⚑ 效果 kind=frag_destroy 已降级：kind 不在效果注册表里
]==]
local s,id=GetID()
function s.initial_effect(c)
	--仪式召唤流程：祭品等级合计不小于 13（签名 c,filter,lv,desc —— desc 不传，传 0 会让 Lua 当成真值去 SetDescription(0)）
	Ritual.AddProcGreater(c,aux.TRUE,13)
	c:EnableReviveLimit()
	-- [CardForge] 效果 kind=frag_destroy 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：①：乱码 ñ中文
end
s.listed_series={0x1001, 0x2}
