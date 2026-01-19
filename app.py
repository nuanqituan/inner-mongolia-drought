import streamlit as st
import leafmap.foliumap as leafmap
import geopandas as gpd
import rioxarray
import xarray as xr
import os
import numpy as np
import pandas as pd
import altair as alt

# ==========================================
# 1. 基础设置
# ==========================================
st.set_page_config(page_title="内蒙古干旱监测系统", layout="wide")
st.title("内蒙古干旱监测与预警系统")

# ==========================================
# 2. 数据连接配置
# ==========================================
USER_NAME = "nuanqituan" 
REPO_NAME = "inner-mongolia-drought"
DATA_PATH = "data" 

# 矢量文件路径
LEAGUE_PATH = f"{DATA_PATH}/inner_mongolia_city.json"      
BANNER_PATH = f"{DATA_PATH}/inner_mongolia_banners.json"   
BOUNDARY_PATH = f"{DATA_PATH}/inner_mongolia_boundary.json" 

@st.cache_data
def load_data():
    if not os.path.exists(LEAGUE_PATH): return None, None
    try:
        leagues_gdf = gpd.read_file(LEAGUE_PATH)
        banners_gdf = gpd.read_file(BANNER_PATH)
        return leagues_gdf, banners_gdf
    except: return None, None

leagues_gdf, banners_gdf = load_data()

if leagues_gdf is None:
    st.error("❌ 本地数据未找到,请检查 GitHub Desktop 是否成功同步了 data 文件夹。")
    st.stop()

# ==========================================
# 3. 左侧控制面板 (Sidebar)
# ==========================================
st.sidebar.header("🕹️ 参数选择")

# --- A. 区域选择 ---
league_names = sorted(leagues_gdf['name'].unique())
selected_league = st.sidebar.selectbox("📍 选择盟市", ["全区概览"] + list(league_names))

selected_geom = None
zoom_level = 5
center = [44.0, 115.0]

if selected_league != "全区概览":
    league_feature = leagues_gdf[leagues_gdf['name'] == selected_league]
    selected_geom = league_feature.unary_union
    
    filtered_banners = banners_gdf[banners_gdf['ParentCity'] == selected_league]
    banner_names = sorted(filtered_banners['name'].unique())
    
    selected_banner = st.sidebar.selectbox("🚩 选择旗县 (可选)", ["全盟市"] + list(banner_names))
    
    if selected_banner != "全盟市":
        target_feature = filtered_banners[filtered_banners['name'] == selected_banner]
        if not target_feature.empty:
            selected_geom = target_feature.geometry.iloc[0]
            centroid = target_feature.geometry.centroid
            center = [centroid.y.values[0], centroid.x.values[0]]
            zoom_level = 8
    else:
        centroid = league_feature.geometry.centroid
        center = [centroid.y.values[0], centroid.x.values[0]]
        zoom_level = 6

# --- B. 时间选择 ---
st.sidebar.markdown("---")
scale_display = st.sidebar.selectbox("📊 SPEI 尺度", ["1个月 (气象干旱)", "3个月 (农业干旱)", "12个月 (水文干旱)"])
scale_map = {"1个月 (气象干旱)": "01", "3个月 (农业干旱)": "03", "12个月 (水文干旱)": "12"}
sel_scale = scale_map[scale_display]

sel_year = st.sidebar.slider("📅 年份", 1950, 2025, 2024)
sel_month = st.sidebar.select_slider("🗓️ 月份", range(1, 13), 8)

month_str = f"{sel_month:02d}"
tif_file = f"{DATA_PATH}/SPEI_{sel_scale}_{sel_year}_{month_str}.tif"


# ==========================================
# 布局分割：地图区 vs 统计区
# ==========================================
# 创建两列：左边宽(地图)，右边窄(统计)
# ratio=[3, 1] 表示地图占 75%，统计占 25%
col_map, col_stats = st.columns([3, 1])


# ==========================================
# 4. 地图展示 (放入左侧大列 col_map)
# ==========================================
with col_map:
    st.subheader(f"🗺️ 分析视图: {selected_league}")
    
    # 创建地图
    m = leafmap.Map(center=center, zoom=zoom_level, locate_control=False, draw_control=False)

    # 1. 显示内蒙古轮廓
    try:
        m.add_geojson(BOUNDARY_PATH, layer_name="内蒙古轮廓", 
                      style={"fillOpacity": 0, "color": "#333333", "weight": 2})
    except: pass

    # 2. 加载SPEI数据
    if not os.path.exists(tif_file):
        st.warning(f"⚠️ 暂无该月份数据: {tif_file}")
    else:
        try:
            # === 读取栅格数据 ===
            xds = rioxarray.open_rasterio(tif_file)
            
            # 裁剪 (如果选了区域)
            if selected_geom is not None:
                try:
                    xds = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
                    # 添加选中区域边界
                    m.add_gdf(gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                              layer_name="选中区域", 
                              style={"fillOpacity": 0, "color": "#0066ff", "weight": 3})
                except:
                    st.warning("区域边缘裁剪微调...")

            # === 关键步骤：处理数据以去除红色背景 ===
            xds_masked = xds.where(xds > -10)
            
            # 保存临时文件
            temp_tif = "temp_display.tif"
            xds_masked.rio.to_raster(temp_tif)
            
            # === 使用 add_raster ===
            m.add_raster(
                temp_tif,
                layer_name="SPEI干旱指数",
                colormap='RdBu',
                vmin=-3,
                vmax=3,
                nodata=np.nan
            )
            
            # 清理
            try: os.remove(temp_tif)
            except: pass
            
            # 添加图例
            m.add_colormap(label="SPEI Index", vmin=-3, vmax=3, palette='RdBu')

        except Exception as e:
            st.error(f"❌ 数据加载出错: {e}")

    # 显示地图 (高度稍微调高一点以匹配右侧内容)
    m.to_streamlit(height=700)


# ==========================================
# 5. 统计信息面板 (放入右侧小列 col_stats)
# ==========================================
with col_stats:
    st.markdown("### 📊 统计概览")
    st.write(f"**时间**: {sel_year}年{sel_month}月")
    
    if os.path.exists(tif_file):
        try:
            # 读取并计算统计数据
            xds_stats = rioxarray.open_rasterio(tif_file)
            if selected_geom is not None:
                xds_stats = xds_stats.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
            
            data_stats = xds_stats.values[0]
            data_stats = np.where(data_stats > -10, data_stats, np.nan)
            valid = data_stats[~np.isnan(data_stats)]
            
            if len(valid) > 0:
                # --- 基础数值 (使用两列布局，防止在窄栏中挤压) ---
                st.markdown("#### 📉 基础指标")
                c1, c2 = st.columns(2)
                c1.metric("最小值", f"{np.min(valid):.2f}")
                c2.metric("最大值", f"{np.max(valid):.2f}")
                
                c3, c4 = st.columns(2)
                c3.metric("平均值", f"{np.mean(valid):.2f}")
                c4.metric("像素数", f"{len(valid)}")
                
                # --- 干旱等级分布 ---
                st.markdown("---")
                st.markdown("#### 🌵 等级占比")
                
                # 计算数量
                extreme_drought = int(np.sum(valid < -2))
                severe_drought = int(np.sum((valid >= -2) & (valid < -1.5)))
                moderate_drought = int(np.sum((valid >= -1.5) & (valid < -1)))
                normal = int(np.sum((valid >= -1) & (valid <= 1)))
                wet = int(np.sum(valid > 1))
                
                # Altair 统计图 (调整为垂直方向更适合侧边)
                chart_data = pd.DataFrame({
                    '等级': ['极端干旱', '严重干旱', '中度干旱', '正常', '湿润'],
                    '像素数': [extreme_drought, severe_drought, moderate_drought, normal, wet],
                    '颜色': ['#ca0020', '#f4a582', '#fddbc7', '#f7f7f7', '#0571b0']
                })
                
                # 创建图表 (去掉 X 轴标题以节省空间)
                chart = alt.Chart(chart_data).mark_bar().encode(
                    x=alt.X('像素数', title=None), 
                    y=alt.Y('等级', sort=None, title=None),
                    color=alt.Color('颜色', scale=None, legend=None),
                    tooltip=['等级', '像素数']
                ).properties(
                    height=250 # 高度适中
                )
                
                st.altair_chart(chart, use_container_width=True)

                # 以文字列表形式补充具体占比 (因为图表没地方显示百分比)
                total = len(valid)
                st.caption(f"🔴 极端干旱: {100*extreme_drought/total:.1f}%")
                st.caption(f"🟠 严重干旱: {100*severe_drought/total:.1f}%")
                st.caption(f"🟡 中度干旱: {100*moderate_drought/total:.1f}%")
                
        except Exception as e:
            st.info("统计数据计算中...")
            # st.error(f"{e}") # 调试用
    else:
        st.write("暂无数据")