--[==[ c210000728
     CardForge 2.0 生成 · 卡种=仪式（frame=ritual） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
]==]
local s,id=GetID()
function s.initial_effect(c)
	--仪式召唤流程：祭品等级合计不小于 0（签名 c,filter,lv,desc —— desc 不传，传 0 会让 Lua 当成真值去 SetDescription(0)）
	Ritual.AddProcGreater(c,aux.TRUE,0)
	c:EnableReviveLimit()
end
s.listed_series={0x1001, 0x2}
