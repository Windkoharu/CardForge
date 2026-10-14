--[==[ c210000744
     CardForge 2.0 生成 · 卡种=同步（frame=synchro） · tier=1
     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。
]==]
local s,id=GetID()
function s.initial_effect(c)
	--同步素材条件：恰好 1 只协调 + 1 只以上非协调（新签名 f1,min1,max1,f2,min2,max2；f2 用 NonTuner 保证非协调不会被协调顶替）
	Synchro.AddProcedure(c,nil,1,1,Synchro.NonTuner(nil),1,99)
	c:EnableReviveLimit()
end
s.listed_series={0x9, 0x63}
