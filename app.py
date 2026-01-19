import streamlit as st
import leafmap.foliumap as leafmap
import geopandas as gpd
import rioxarray
import xarray as xr
import os
import matplotlib.pyplot as plt
import numpy as np

# ==========================================
# 1. 基础设置
# ==========================================
st.set_page_config(page_title="内蒙古干旱监测系统", layout="wide")
st.title("内蒙古干旱监测与预警系统")

# ==========================================
# 2. 数据连接配置
# ==========================================
# ！！！请务必修改下面这一行！！！
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
    st.error("❌ 本地数据未找到，请检查 GitHub Desktop 是否成功同步了 data 文件夹。")
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
# 4. 地图展示核心逻辑 (PNG贴图版)
# ==========================================
st.subheader(f"分析视图: {selected_league} - {sel_year}年{sel_month}月")

m = leafmap.Map(center=center, zoom=zoom_level)

# 1. 显示内蒙古轮廓
try:
    m.add_geojson(BOUNDARY_PATH, layer_name="内蒙古轮廓", style={"fillOpacity": 0, "color": "#333333", "weight": 2})
except: pass 

# 2. 加载数据
if not os.path.exists(tif_file):
    st.warning(f"⚠️ 暂无该月份数据")
else:
    try:
        # 读取数据
        xds = rioxarray.open_rasterio(tif_file)
        
        # 裁剪 (如果选了区域)
        if selected_geom is not None:
             xds = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
             # 加个蓝色框
             m.add_gdf(gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                      layer_name="边界", style={"fillOpacity": 0, "color": "blue", "weight": 2})

        # --- 核心黑科技：手动生成一张 PNG 图片 ---
        # 1. 提取数值
        data = xds.values[0] # 取第一波段
        
        # 2. 过滤背景 (把小于-10的值设为 NaN)
        data = np.where(data > -10, data, np.nan)

        # 3. 数据侦探
        valid_data = data[~np.isnan(data)]
        if len(valid_data) > 0:
            st.sidebar.success(f"🔍 数据范围: {np.nanmin(data):.2f} ~ {np.nanmax(data):.2f}")
        else:
            st.warning("该区域当前月份无有效数据")

        # 4. 上色 (把数值变成颜色)
        # 归一化 (-3 到 3)
        norm = plt.Normalize(vmin=-3, vmax=3)
        cmap = plt.cm.RdBu # 红蓝配色
        
        # 生成 RGBA 图片矩阵
        rgba_img = cmap(norm(data))
        
        # 5. 设置透明度 (关键！)
        # 所有 NaN (背景) 的地方，透明度设为 0
        rgba_img[..., 3] = np.where(np.isnan(data), 0, 1)
        
        # 6. 保存为临时 PNG
        temp_png = "temp_map.png"
        plt.imsave(temp_png, rgba_img)
        
        # 7. 计算图片在地图上的坐标范围
        # rioxarray 的 bounds 是 (minx, miny, maxx, maxy) -> (lon_min, lat_min, lon_max, lat_max)
        b = xds.rio.bounds()
        # leafmap 需要 [[lat_min, lon_min], [lat_max, lon_max]]
        bounds = [[b[1], b[0]], [b[3], b[2]]]
        
        # 8. 贴图！
        m.add_image(temp_png, bounds=bounds, layer_name="干旱等级")
        
        # 9. 手动添加图例图片 (可选，防止之前的报错)
        m.add_colormap(label="SPEI Index", vmin=-3, vmax=3, palette='RdBu')

    except Exception as e:
        st.error(f"渲染出错: {e}")

m.to_streamlit(height=650)