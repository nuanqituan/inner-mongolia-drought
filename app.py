import streamlit as st
import leafmap.foliumap as leafmap
import geopandas as gpd
import rioxarray
import xarray as xr
import os
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

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
# 4. 地图展示核心逻辑 (修复版)
# ==========================================
st.subheader(f"分析视图: {selected_league} - {sel_year}年{sel_month}月")

# 添加调试开关
debug_mode = st.sidebar.checkbox("🔍 调试模式", value=True)

m = leafmap.Map(center=center, zoom=zoom_level)

# 1. 显示内蒙古轮廓
try:
    m.add_geojson(BOUNDARY_PATH, layer_name="内蒙古轮廓", style={"fillOpacity": 0, "color": "#333333", "weight": 2})
except: 
    if debug_mode:
        st.warning("无法加载边界文件")

# 2. 加载数据
if not os.path.exists(tif_file):
    st.warning(f"⚠️ 暂无该月份数据: {tif_file}")
else:
    try:
        # 读取数据
        if debug_mode:
            st.info(f"✅ 正在读取文件: {tif_file}")
        
        xds = rioxarray.open_rasterio(tif_file)
        
        if debug_mode:
            st.write(f"📊 原始数据维度: {xds.shape}")
            st.write(f"📍 坐标范围: {xds.rio.bounds()}")
        
        # 裁剪 (如果选了区域)
        if selected_geom is not None:
            xds = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
            m.add_gdf(gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                     layer_name="选中区域", style={"fillOpacity": 0, "color": "blue", "weight": 2})
            
            if debug_mode:
                st.write(f"✂️ 裁剪后维度: {xds.shape}")

        # 提取数值
        data = xds.values[0]
        
        # 过滤无效值 (SPEI通常范围在-3到3之间,小于-10的一定是背景)
        data_filtered = np.where(data > -10, data, np.nan)
        
        # 数据统计
        valid_data = data_filtered[~np.isnan(data_filtered)]
        
        if len(valid_data) == 0:
            st.error("❌ 该区域当前月份无有效数据!")
        else:
            if debug_mode:
                st.sidebar.success(f"✅ 有效像素: {len(valid_data)}")
                st.sidebar.info(f"📈 数据范围: {np.nanmin(data_filtered):.2f} ~ {np.nanmax(data_filtered):.2f}")
                st.sidebar.info(f"📊 平均值: {np.nanmean(data_filtered):.2f}")
            
            # === 方法1: 使用leafmap自带的add_raster ===
            # 这个方法更稳定,推荐使用
            try:
                # 创建临时GeoTIFF
                temp_tif = "temp_clipped.tif"
                xds.rio.to_raster(temp_tif)
                
                # 使用leafmap的add_raster方法
                m.add_raster(
                    temp_tif,
                    layer_name="SPEI干旱指数",
                    colormap="RdBu",  # 红蓝配色: 红=干旱,蓝=湿润
                    vmin=-3,
                    vmax=3,
                    nodata=-9999
                )
                
                if debug_mode:
                    st.success("✅ 使用 add_raster 方法渲染")
                
                # 清理临时文件
                if os.path.exists(temp_tif):
                    os.remove(temp_tif)
                    
            except Exception as e1:
                if debug_mode:
                    st.warning(f"add_raster 失败: {e1}, 尝试备用方案...")
                
                # === 方法2: 手动生成PNG (备用方案) ===
                try:
                    # 归一化到0-1
                    data_norm = (data_filtered - (-3)) / (3 - (-3))
                    data_norm = np.clip(data_norm, 0, 1)
                    
                    # 使用RdBu配色
                    cmap = plt.cm.RdBu
                    rgba = cmap(data_norm)
                    
                    # 设置透明度: NaN的地方完全透明
                    alpha = np.where(np.isnan(data_filtered), 0, 0.7)  # 有效数据70%透明度
                    rgba[..., 3] = alpha
                    
                    # 保存PNG
                    temp_png = "temp_spei.png"
                    
                    # 转换为8位图像
                    rgba_uint8 = (rgba * 255).astype(np.uint8)
                    img = Image.fromarray(rgba_uint8, mode='RGBA')
                    img.save(temp_png)
                    
                    # 获取地理范围
                    bounds = xds.rio.bounds()
                    bounds_leaflet = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]
                    
                    # 添加到地图
                    m.add_image(temp_png, bounds=bounds_leaflet, layer_name="SPEI干旱指数")
                    
                    if debug_mode:
                        st.success("✅ 使用 PNG 方法渲染")
                    
                    # 清理
                    if os.path.exists(temp_png):
                        os.remove(temp_png)
                        
                except Exception as e2:
                    st.error(f"❌ PNG渲染也失败: {e2}")
            
            # 添加图例
            try:
                # 干旱等级说明
                legend_dict = {
                    '极端湿润 (>2)': '#0571b0',
                    '严重湿润 (1.5~2)': '#92c5de',
                    '中度湿润 (1~1.5)': '#d1e5f0',
                    '正常 (-1~1)': '#f7f7f7',
                    '中度干旱 (-1.5~-1)': '#fddbc7',
                    '严重干旱 (-2~-1.5)': '#f4a582',
                    '极端干旱 (<-2)': '#ca0020'
                }
                m.add_legend(title="SPEI干旱等级", legend_dict=legend_dict)
            except:
                pass

    except Exception as e:
        st.error(f"❌ 数据处理出错: {e}")
        if debug_mode:
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
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("最小值", f"{np.min(valid):.2f}")
            col2.metric("平均值", f"{np.mean(valid):.2f}")
            col3.metric("最大值", f"{np.max(valid):.2f}")
            col4.metric("有效像素", f"{len(valid)}")
            
            # 干旱等级统计
            extreme_drought = np.sum(valid < -2)
            severe_drought = np.sum((valid >= -2) & (valid < -1.5))
            moderate_drought = np.sum((valid >= -1.5) & (valid < -1))
            
            st.markdown("### 干旱面积占比")
            drought_col1, drought_col2, drought_col3 = st.columns(3)
            drought_col1.metric("极端干旱", f"{100*extreme_drought/len(valid):.1f}%")
            drought_col2.metric("严重干旱", f"{100*severe_drought/len(valid):.1f}%")
            drought_col3.metric("中度干旱", f"{100*moderate_drought/len(valid):.1f}%")
    except:
        pass