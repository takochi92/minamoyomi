"""乗り手補正つきモーター評価の検証（公式の過去データだけを使う）。

  python -m tools.rider_adjust_eval            # 表を作って検証結果を表示

乗り手が替わった「次の節」の成績を、前の乗り手までの数字からどれだけ当てられるかを比べる。
前半の期間で重みを決め、後半の期間（未使用）で確かめる。結果の読み方は research/improvements/RIDER_ADJUSTED_MOTOR.md。
"""

from collections import defaultdict
from datetime import date


import numpy as np

from scraper.history import load_all


def build_runs():
    rs=sorted(load_all(""),key=lambda r:(r[0],r[1],r[2]))
    ordn=lambda d:date(int(d[:4]),int(d[4:6]),int(d[6:])).toordinal()
    # 世代：その日の出走表のモーター2連率がほぼ全艇0 → 新しいモーター（3日より前に同じ状態がなければ切替）
    zero=defaultdict(lambda:[0,0])
    for r in rs:
        for e in r[11]:
            b=e[7] if len(e)>7 else None
            if b and len(b)>5 and b[5] is not None:
                z=zero[(r[1],r[0])];z[0]+=1;z[1]+=int(b[5]==0)
    gen=defaultdict(int);last={};genof={}
    for (j,d) in sorted(zero,key=lambda k:(k[1],k[0])):
        n,z=zero[(j,d)]
        if n>=24 and z/n>=.9:
            t=ordn(d)
            if t-last.get(j,-99)>3:gen[j]+=1
            last[j]=t
        genof[(j,d)]=gen[j]
    rows=[];nomotor=0;noex=0
    for ri,r in enumerate(rs):
        E=r[11]
        if len(E)!=6 or {e[0] for e in E}!=set(range(1,7)):continue
        ex=[e[6] if len(e)>6 else None for e in E]
        okex=all(isinstance(x,(int,float)) and 0<x<1000 for x in ex)
        mean=sum(ex)/6 if okex else None
        for e in E:
            mno=e[8] if len(e)>8 else None
            b=e[7] if len(e)>7 else None
            if not b:continue
            if mno is None:nomotor+=1;mno=-1
            if not okex:noex+=1
            place=e[5] if isinstance(e[5],int) else 7
            rows.append((int(r[1]),ordn(r[0]),ri,e[0],int(e[1]),int(mno),genof.get((r[1],r[0]),0),
                         (e[6]-mean)/100 if okex else np.nan, e[2] or 0, place, b[1] or 0.0, {'A1':0,'A2':1,'B1':2,'B2':3}.get(b[0],3), b[5] if len(b)>5 and b[5] is not None else np.nan))
    A=np.array(rows,dtype=float)
    cols=['venue','day','race','frame','toban','motor','gen','dev','course','place','natwin','cls','m2']
    return cols, A


def evaluate(cols, A):
    C={c:i for i,c in enumerate(cols)}
    A=A[np.lexsort((A[:,C['race']],A[:,C['day']]))]
    venue,day,toban,motor,gen,dev,course,place,cls,m2=(A[:,C[k]] for k in ('venue','day','toban','motor','gen','dev','course','place','cls','m2'))
    ok=~np.isnan(dev)
    exp=defaultdict(lambda:[0,0,0,0])
    for c,k,p in zip(course,cls,place):e=exp[(c,k)];e[0]+=1;e[1]+=p<=3;e[2]+=p<=2;e[3]+=p==1
    t3=(place<=3).astype(float);t2=(place<=2).astype(float);w1=(place==1).astype(float)
    e3=np.array([exp[(c,k)][1]/exp[(c,k)][0] for c,k in zip(course,cls)]);e2=np.array([exp[(c,k)][2]/exp[(c,k)][0] for c,k in zip(course,cls)]);e1=np.array([exp[(c,k)][3]/exp[(c,k)][0] for c,k in zip(course,cls)])
    res=t3-e3
    KR,RHL=8,180
    rb=np.zeros(len(A));rr=np.zeros(len(A));acc=defaultdict(lambda:[0.,0.,0.,0.,0.]);i=0;n=len(A)
    while i<n:
        j=i
        while j<n and day[j]==day[i]:j+=1
        for k in range(i,j):
            a=acc[toban[k]];f=0.5**((day[k]-a[4])/RHL) if a[4] else 1.
            rb[k]=a[1]*f/(a[0]*f+KR);rr[k]=a[3]*f/(a[2]*f+KR)
        for k in range(i,j):
            a=acc[toban[k]]
            if a[4]:
                f=0.5**((day[k]-a[4])/RHL)
                for q in range(4):a[q]*=f
            if ok[k]:a[0]+=1;a[1]+=dev[k]
            a[2]+=1;a[3]+=res[k];a[4]=day[k]
        i=j
    by=defaultdict(list)
    for k in np.where(motor>=0)[0]:by[(venue[k],gen[k],motor[k])].append(k)
    X=[]
    for key,ks in by.items():
        L=[];cur=None
        for k in ks:
            if cur is None or toban[k]!=cur[0] or day[k]-cur[2]>2:cur=[toban[k],day[k],day[k],[]];L.append(cur)
            cur[3].append(k);cur[2]=day[k]
        st=[]
        for t,f,l,kk in L:
            kk=np.array(kk);o=ok[kk]
            st.append(dict(t=t,first=f,n=int(o.sum()),nr=len(kk),dev=float(dev[kk][o].mean()) if o.any() else 0.,rb=rb[kk[0]],rr=rr[kk[0]],res=float(res[kk].mean()),
                           t3=t3[kk].sum(),e3=e3[kk].sum(),t2=t2[kk].sum(),e2=e2[kk].sum(),w1=w1[kk].sum(),e1=e1[kk].sum(),m2=m2[kk[0]]))
        for ti in range(1,len(st)):
            g=st[ti]
            if g['nr']<4:continue
            prev=[p for p in st[:ti] if p['t']!=g['t']]
            if sum(p['n'] for p in prev)<12:continue
            def w(HL,key='n'):return np.array([p[key]*0.5**((g['first']-p['first'])/HL) if HL else p[key] for p in prev])
            f=lambda ww,vals,K:float((ww*vals).sum()/(ww.sum()+K))
            d=np.array([p['dev'] for p in prev]);r_=np.array([p['rb'] for p in prev]);rs=np.array([p['res'] for p in prev]);rrs=np.array([p['rr'] for p in prev])
            X.append((g['first'],key[0],
                      f(w(None),d,10),            # 2 補正なし・全期間
                      f(w(14),d,6),               # 3 いまの本番に近い形（補正なし・半減14日）
                      f(w(45),d,6),               # 4 補正なし・半減45日
                      f(w(45),d-r_,6),            # 5 乗り手補正・半減45日
                      f(w(90,'nr'),rs-rrs,10),    # 6 着順の乗り手補正・半減90日
                      g['m2'],                    # 7 公式モーター2連率（その節の初日の出走表）
                      g['res'],g['t3'],g['e3'],g['t2'],g['e2'],g['w1'],g['e1'],g['nr'],g['dev']-g['rb']))
    X=np.array(X);X=X[~np.isnan(X[:,7])]
    med=np.median(X[:,0]);tr=X[:,0]<med;te=~tr
    print("乗り替わり",len(X),"（学習 前半",tr.sum(),"／検証 後半",te.sum(),"）")
    names={2:"展示・補正なし（全期間）",3:"展示・補正なし（半減14日＝いまの本番に近い）",4:"展示・補正なし（半減45日）",5:"展示・乗り手補正（半減45日）",6:"着順・乗り手補正",7:"公式モーター2連率"}
    sg={2:-1,3:-1,4:-1,5:-1,6:1,7:1}
    cor=lambda a,b:np.corrcoef(a,b)[0,1]
    print("\n次の乗り手の成績（3着内−期待）との相関 ［検証＝後半］")
    for c in names:print(f"  {names[c]:28s} r={cor(sg[c]*X[te,c],X[te,8]):.3f}")
    # 組み合わせ：前半で重みを決め、後半で試す
    def fit(colsx):
        Z=np.c_[np.ones(tr.sum()),(X[tr][:,colsx]-X[tr][:,colsx].mean(0))/X[tr][:,colsx].std(0)]
        b=np.linalg.lstsq(Z,X[tr,8],rcond=None)[0]
        Zt=np.c_[np.ones(te.sum()),(X[te][:,colsx]-X[tr][:,colsx].mean(0))/X[tr][:,colsx].std(0)]
        return Zt@b,b
    combos={"公式2連率だけ":[7],"展示（補正なし）＋公式2連率":[4,7],"展示（乗り手補正）＋着順（乗り手補正）":[5,6],"展示補正＋着順補正＋公式2連率":[5,6,7]}
    preds={}
    for n_,cc in combos.items():
        p,b=fit(cc);preds[n_]=p;print(f"  組み合わせ {n_:30s} r={cor(p,X[te,8]):.3f}")
    def quint(score,label):
        T=X[te];o=np.argsort(-score);k=len(o)//5
        print(f"\n{label}：上位20%〜下位20%の5段（検証＝後半、次の乗り手の実績）")
        for q,nm in enumerate(["上位20%","20-40%","40-60%","60-80%","下位20%"]):
            s=o[q*k:(q+1)*k] if q<4 else o[4*k:]
            nr=T[s,15].sum()
            print(f"   {nm}: 3着内 {T[s,9].sum()/nr*100:5.1f}%（期待 {T[s,10].sum()/nr*100:4.1f}%）差 {(T[s,9].sum()-T[s,10].sum())/nr*100:+5.1f}  1着 {T[s,13].sum()/nr*100:5.1f}%（期待 {T[s,14].sum()/nr*100:4.1f}%）差 {(T[s,13].sum()-T[s,14].sum())/nr*100:+5.1f}")
    quint(X[te,7],"公式モーター2連率")
    quint(-X[te,3],"展示・補正なし・半減14日（いまの本番に近い）")
    quint(-X[te,5],"展示・乗り手補正（半減45日）")
    quint(preds["展示（乗り手補正）＋着順（乗り手補正）"],"展示補正＋着順補正（新しい総合の案）")
    quint(preds["展示補正＋着順補正＋公式2連率"],"展示補正＋着順補正＋公式2連率")


if __name__ == "__main__":
    evaluate(*build_runs())
