import streamlit as st
import leafmap.foliumap as leafmap
import geopandas as gpd
import rioxarray
import xarray as xr
import os
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
from io import BytesIO
import base64

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
# 3. 左侧控制面板
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
# 4. 地图展示核心逻辑 (强化版)
# ==========================================
st.subheader(f"分析视图: {selected_league} - {sel_year}年{sel_month}月")

# 创建地图
m = leafmap.Map(center=center, zoom=zoom_level, locate_control=False, draw_control=False)

# 1. 显示内蒙古轮廓
try:
    m.add_geojson(BOUNDARY_PATH, layer_name="内蒙古轮廓", 
                  style={"fillOpacity": 0, "color": "#333333", "weight": 2})
except: 
    pass

# 2. 加载SPEI数据
if not os.path.exists(tif_file):
    st.warning(f"⚠️ 暂无该月份数据: {tif_file}")
else:
    try:
        # === 读取栅格数据 ===
        xds = rioxarray.open_rasterio(tif_file)
        
        # 获取原始边界
        original_bounds = xds.rio.bounds()
        
        # 裁剪 (如果选了区域)
        if selected_geom is not None:
            xds = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
            # 添加选中区域边界
            m.add_gdf(gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                     layer_name="选中区域", 
                     style={"fillOpacity": 0, "color": "#0066ff", "weight": 3})
        
        # === 数据处理 ===
        data = xds.values[0]  # 获取第一波段
        
        # 过滤无效值 (SPEI通常 > -10)
        data_clean = np.where(data > -10, data, np.nan)
        
        # 统计有效数据
        valid_mask = ~np.isnan(data_clean)
        valid_data = data_clean[valid_mask]
        
        if len(valid_data) == 0:
            st.error("❌ 该区域当前月份无有效数据!")
        else:
            # 显示数据统计
            st.sidebar.success(f"✅ 有效像素: {len(valid_data)}")
            st.sidebar.info(f"📊 SPEI范围: {np.nanmin(data_clean):.2f} ~ {np.nanmax(data_clean):.2f}")
            
            # === 核心修复: 使用folium的ImageOverlay ===
            # 1. 创建配色方案 (RdBu: 红=干旱, 蓝=湿润)
            cmap = plt.cm.RdBu
            norm = mcolors.Normalize(vmin=-3, vmax=3)
            
            # 2. 将数据映射到颜色 (RGBA格式)
            rgba_array = cmap(norm(data_clean))
            
            # 3. 设置透明度: 有效数据=不透明, 背景=透明
            alpha_channel = np.where(valid_mask, 0.75, 0.0)  # 75%不透明度
            rgba_array[..., 3] = alpha_channel
            
            # 4. 翻转Y轴 (重要! leaflet坐标系与numpy相反)
            rgba_array = np.flipud(rgba_array)
            
            # 5. 转换为图片
            from PIL import Image
            height, width = rgba_array.shape[:2]
            img = Image.fromarray((rgba_array * 255).astype(np.uint8), mode='RGBA')
            
            # 6. 保存为临时文件
            temp_png = "temp_spei_overlay.png"
            img.save(temp_png, format='PNG')
            
            # 7. 获取地理边界 (leaflet格式: [[south, west], [north, east]])
            bounds = xds.rio.bounds()  # (west, south, east, north)
            leaflet_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]  # [[south, west], [north, east]]
            
            # 8. 添加图片到地图
            import folium
            img_overlay = folium.raster_layers.ImageOverlay(
                image=temp_png,
                bounds=leaflet_bounds,
                opacity=0.75,
                name='SPEI干旱指数'
            )
            img_overlay.add_to(m)
            
            st.success("✅ SPEI数据渲染成功!")
            
            # 清理临时文件
            try:
                os.remove(temp_png)
            except:
                pass
            
            # === 添加图例 ===
            legend_html = '''
            <div style="position: fixed; 
                        bottom: 50px; right: 50px; width: 200px;
                        background-color: white; z-index:9999; font-size:14px;
                        border:2px solid grey; border-radius: 5px; padding: 10px">
                <p style="margin:0; font-weight:bold; text-align:center;">SPEI干旱等级</p>
                <p style="margin:5px 0;"><span style="background:#ca0020; padding:2px 10px;">&nbsp;&nbsp;</span> 极端干旱 (&lt;-2)</p>
                <p style="margin:5px 0;"><span style="background:#f4a582; padding:2px 10px;">&nbsp;&nbsp;</span> 严重干旱 (-2~-1.5)</p>
                <p style="margin:5px 0;"><span style="background:#fddbc7; padding:2px 10px;">&nbsp;&nbsp;</span> 中度干旱 (-1.5~-1)</p>
                <p style="margin:5px 0;"><span style="background:#f7f7f7; padding:2px 10px;">&nbsp;&nbsp;</span> 正常 (-1~1)</p>
                <p style="margin:5px 0;"><span style="background:#d1e5f0; padding:2px 10px;">&nbsp;&nbsp;</span> 中度湿润 (1~1.5)</p>
                <p style="margin:5px 0;"><span style="background:#92c5de; padding:2px 10px;">&nbsp;&nbsp;</span> 严重湿润 (1.5~2)</p>
                <p style="margin:5px 0;"><span style="background:#0571b0; padding:2px 10px;">&nbsp;&nbsp;</span> 极端湿润 (&gt;2)</p>
            </div>
            '''
            m.get_root().html.add_child(folium.Element(legend_html))

    except Exception as e:
        st.error(f"❌ 数据处理出错: {e}")
        import traceback
        st.code(traceback.format_exc())

# 显示地图
m.to_streamlit(height=650)

# ==========================================
# 5. 统计信息面板
# ==========================================
if os.path.exists(tif_file):
    try:
        xds_stats = rioxarray.open_rasterio(tif_file)
        if selected_geom is not None:
            xds_stats = xds_stats.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
        
        data_stats = xds_stats.values[0]
        data_stats = np.where(data_stats > -10, data_stats, np.nan)
        valid = data_stats[~np.isnan(data_stats)]
        
        if len(valid) > 0:
            st.markdown("---")
            st.markdown("### 📊 统计信息")
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("最小值", f"{np.min(valid):.2f}")
            col2.metric("平均值", f"{np.mean(valid):.2f}")
            col3.metric("最大值", f"{np.max(valid):.2f}")
            col4.metric("有效像素", f"{len(valid)}")
            
            # 干旱等级统计
            extreme_drought = np.sum(valid < -2)
            severe_drought = np.sum((valid >= -2) & (valid < -1.5))
            moderate_drought = np.sum((valid >= -1.5) & (valid < -1))
            
            st.markdown("### 🌵 干旱面积占比")
            drought_col1, drought_col2, drought_col3 = st.columns(3)
            drought_col1.metric("极端干旱", f"{100*extreme_drought/len(valid):.1f}%", 
                              delta=None, delta_color="inverse")
            drought_col2.metric("严重干旱", f"{100*severe_drought/len(valid):.1f}%",
                              delta=None, delta_color="inverse")
            drought_col3.metric("中度干旱", f"{100*moderate_drought/len(valid):.1f}%",
                              delta=None, delta_color="inverse")
    except:
        pass