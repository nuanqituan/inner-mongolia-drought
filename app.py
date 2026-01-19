import streamlit as st
import leafmap.foliumap as leafmap
import geopandas as gpd
import rioxarray
import xarray as xr
import os
import numpy as np
import pandas as pd
import altair as alt
from PIL import Image
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import folium

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

LEAGUE_PATH = f"{DATA_PATH}/inner_mongolia_city.json"      
BANNER_PATH = f"{DATA_PATH}/inner_mongolia_banners.json"   
BOUNDARY_PATH = f"{DATA_PATH}/inner_mongolia_boundary.json" 

# === 🎯 坐标硬校准 (根据您的反馈) ===
# 现象：地图整体偏北 2 个像元
# 分辨率：0.25度
# 修正计算： 0.25 = 0.5度
# 修正方向：向下（向南），即 纬度减去 0.25
FIX_LAT_OFFSET = -0.25  # 向南平移 0.5 度
FIX_LON_OFFSET = 0.0   # 经度保持不变

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
# 3. 左侧控制面板
# ==========================================
st.sidebar.header("🕹️ 参数选择")

# --- 区域选择 ---
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

# --- 时间选择 ---
st.sidebar.markdown("---")
scale_display = st.sidebar.selectbox("📊 SPEI 尺度", ["1个月 (气象干旱)", "3个月 (农业干旱)", "12个月 (水文干旱)"])
scale_map = {"1个月 (气象干旱)": "01", "3个月 (农业干旱)": "03", "12个月 (水文干旱)": "12"}
sel_scale = scale_map[scale_display]

sel_year = st.sidebar.slider("📅 年份", 1950, 2025, 2024)
sel_month = st.sidebar.select_slider("🗓️ 月份", range(1, 13), 8)

month_str = f"{sel_month:02d}"
tif_file = f"{DATA_PATH}/SPEI_{sel_scale}_{sel_year}_{month_str}.tif"

# ==========================================
# 4. 布局结构 (左右分栏)
# ==========================================
col_map, col_stats = st.columns([3, 1])

# ==========================================
# 5. 地图展示核心逻辑 (PNG贴图 + 硬校准)
# ==========================================
with col_map:
    st.subheader(f"🗺️ 分析视图: {selected_league}")
    m = leafmap.Map(center=center, zoom=zoom_level, locate_control=False, draw_control=False)

    # 显示边界
    try:
        m.add_geojson(BOUNDARY_PATH, layer_name="内蒙古轮廓", 
                      style={"fillOpacity": 0, "color": "#333333", "weight": 2})
    except: pass

    if not os.path.exists(tif_file):
        st.warning(f"⚠️ 暂无该月份数据")
    else:
        try:
            # === 读取数据 ===
            xds = rioxarray.open_rasterio(tif_file)
            
            # 不重投影，只赋予坐标系
            if xds.rio.crs is None:
                xds = xds.rio.write_crs("EPSG:4326")

            # 裁剪
            if selected_geom is not None:
                try:
                    # 注意：如果硬偏移量很大，先裁剪可能会导致边缘切掉一点点
                    # 但0.5度通常还好。为了完美，可以先贴图再加框，但为了速度还是先clip
                    xds = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
                    m.add_gdf(gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                              layer_name="选中区域", style={"fillOpacity": 0, "color": "#0066ff", "weight": 3})
                except: pass

            # === 数据处理 (生成PNG) ===
            data = xds.values[0]
            data_clean = np.where(data > -10, data, np.nan)
            valid_mask = ~np.isnan(data_clean)
            
            if np.any(valid_mask):
                # 渲染颜色
                cmap = plt.cm.RdBu
                norm = mcolors.Normalize(vmin=-3, vmax=3)
                rgba_array = cmap(norm(data_clean))
                rgba_array[..., 3] = np.where(valid_mask, 1.0, 0.0) # 透明度
                
                img = Image.fromarray((rgba_array * 255).astype(np.uint8), mode='RGBA')
                temp_png = "temp_spei_visual.png"
                img.save(temp_png, format='PNG')
                
                # === 坐标应用 (硬编码修正) ===
                bounds = xds.rio.bounds() # (minx, miny, maxx, maxy)
                
                # 直接应用 FIX_LAT_OFFSET (-0.5)
                leaflet_bounds = [
                    [bounds[1] + FIX_LAT_OFFSET, bounds[0] + FIX_LON_OFFSET], # South-West
                    [bounds[3] + FIX_LAT_OFFSET, bounds[2] + FIX_LON_OFFSET]  # North-East
                ]
                
                # 贴图
                img_overlay = folium.raster_layers.ImageOverlay(
                    image=temp_png,
                    bounds=leaflet_bounds,
                    opacity=0.85,
                    interactive=True,
                    cross_origin=False,
                    zindex=1,
                    name='SPEI干旱指数'
                )
                img_overlay.add_to(m)
                
                # 清理
                try: os.remove(temp_png)
                except: pass
                
                # === 分级图例 ===
                legend_html = '''
                <div style="position: fixed; 
                            bottom: 30px; right: 10px; width: 150px;
                            background-color: white; z-index:9999; font-size:12px;
                            border:2px solid grey; border-radius: 5px; padding: 10px">
                    <p style="margin:0; font-weight:bold; text-align:center;">SPEI干旱等级</p>
                    <p style="margin:2px;"><span style="background:#ca0020; padding:0px 8px;">&nbsp;</span> 极端干旱 (&lt;-2)</p>
                    <p style="margin:2px;"><span style="background:#f4a582; padding:0px 8px;">&nbsp;</span> 严重干旱</p>
                    <p style="margin:2px;"><span style="background:#fddbc7; padding:0px 8px;">&nbsp;</span> 中度干旱</p>
                    <p style="margin:2px;"><span style="background:#f7f7f7; padding:0px 8px;">&nbsp;</span> 正常</p>
                    <p style="margin:2px;"><span style="background:#d1e5f0; padding:0px 8px;">&nbsp;</span> 中度湿润</p>
                    <p style="margin:2px;"><span style="background:#92c5de; padding:0px 8px;">&nbsp;</span> 严重湿润</p>
                    <p style="margin:2px;"><span style="background:#0571b0; padding:0px 8px;">&nbsp;</span> 极端湿润 (&gt;2)</p>
                </div>
                '''
                m.get_root().html.add_child(folium.Element(legend_html))
            else:
                st.warning("无有效数据区域")

        except Exception as e:
            st.error(f"地图渲染错误: {e}")

    m.to_streamlit(height=700)

# ==========================================
# 6. 统计信息 (右侧栏)
# ==========================================
with col_stats:
    st.markdown("### 📊 统计概览")
    if os.path.exists(tif_file):
        try:
            # 独立读取统计数据
            xds_stats = rioxarray.open_rasterio(tif_file)
            if selected_geom is not None:
                xds_stats = xds_stats.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
            
            data_s = xds_stats.values[0]
            valid = data_s[(data_s > -10) & (~np.isnan(data_s))]
            
            if len(valid) > 0:
                # 基础数值
                c1, c2 = st.columns(2)
                c1.metric("最低", f"{np.min(valid):.2f}")
                c2.metric("最高", f"{np.max(valid):.2f}")
                st.metric("平均SPEI", f"{np.mean(valid):.2f}")
                
                # 等级统计
                cnts = {
                    '极端干旱': int(np.sum(valid < -2)),
                    '严重干旱': int(np.sum((valid >= -2) & (valid < -1.5))),
                    '中度干旱': int(np.sum((valid >= -1.5) & (valid < -1))),
                    '正常': int(np.sum((valid >= -1) & (valid <= 1))),
                    '湿润': int(np.sum(valid > 1))
                }
                
                # Altair 柱状图
                df_chart = pd.DataFrame({
                    '等级': list(cnts.keys()),
                    '像素': list(cnts.values()),
                    '颜色': ['#ca0020', '#f4a582', '#fddbc7', '#f7f7f7', '#0571b0']
                })
                
                chart = alt.Chart(df_chart).mark_bar().encode(
                    x=alt.X('像素', title=None),
                    y=alt.Y('等级', sort=None, title=None),
                    color=alt.Color('颜色', scale=None, legend=None),
                    tooltip=['等级', '像素']
                ).properties(height=250)
                
                st.markdown("#### 🌵 面积占比")
                st.altair_chart(chart, use_container_width=True)
                
                # 文字占比
                total = len(valid)
                st.caption(f"🔴 极端干旱: {100*cnts['极端干旱']/total:.1f}%")
                st.caption(f"🟠 严重干旱: {100*cnts['严重干旱']/total:.1f}%")
                
        except:
            st.info("统计计算中...")