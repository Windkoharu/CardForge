--[==[ 乱码/\:*?
     CardForge 2.0 生成 · 卡种=连接（frame=link） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
     ⚑ 效果 kind=frag_destroy 已降级：kind 不在效果注册表里
]==]
local s,id=GetID()
function s.initial_effect(c)
	--连接素材条件：1 只以上、合计等于连接值 13
	Link.AddProcedure(c,nil,1,13)
	c:EnableReviveLimit()
	-- [CardForge] 连接怪兽没有连接箭头，请检查 link_markers
	-- [CardForge] 效果 kind=frag_destroy 暂无脚本片段，需人工补写：kind 不在效果注册表里
	-- 原卡文：①：乱码 ñ中文
end
s.listed_series={0x1001}
