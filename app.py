import streamlit as st
import leafmap.foliumap as leafmap
import geopandas as gpd
import rioxarray
import xarray as xr # 引入 xarray 处理数据
import os

# ==========================================
# 1. 基础设置
# ==========================================
st.set_page_config(page_title="内蒙古干旱监测系统", layout="wide")
st.title("内蒙古干旱监测与预警系统")

# ==========================================
# 2. 数据连接配置
# ==========================================
# ！！！请务必修改下面这一行，换成你自己的 GitHub 用户名！！！
USER_NAME = "nuanqituan" 
REPO_NAME = "inner-mongolia-drought"

REPO_URL = f"https://raw.githubusercontent.com/{USER_NAME}/{REPO_NAME}/main/data"

LEAGUE_URL = f"{REPO_URL}/inner_mongolia_city.json"      
BANNER_URL = f"{REPO_URL}/inner_mongolia_banners.json"   
BOUNDARY_URL = f"{REPO_URL}/inner_mongolia_boundary.json" 

@st.cache_data
def load_data():
    try:
        leagues_gdf = gpd.read_file(LEAGUE_URL)
        banners_gdf = gpd.read_file(BANNER_URL)
        return leagues_gdf, banners_gdf
    except Exception as e:
        return None, None

leagues_gdf, banners_gdf = load_data()

if leagues_gdf is None or banners_gdf is None:
    st.error(f"❌ 数据加载失败！请检查 GitHub 用户名 '{USER_NAME}' 是否正确。")
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
tif_url = f"{REPO_URL}/SPEI_{sel_scale}_{sel_year}_{month_str}.tif"

# ==========================================
# 4. 地图展示核心逻辑
# ==========================================
st.subheader(f"分析视图: {selected_league} - {sel_year}年{sel_month}月")

m = leafmap.Map(center=center, zoom=zoom_level)
# SPEI通常在 -2.5 到 2.5 之间。我们在 ArcGIS 截图里看到有 -8.2 的极端值。
# 这里把范围稍微调大一点，避免极端值颜色饱和
vis_params = {'min': -3.0, 'max': 3.0, 'palette': 'RdBu'}

# 1. 显示内蒙古轮廓
try:
    m.add_geojson(BOUNDARY_URL, layer_name="内蒙古轮廓", style={"fillOpacity": 0, "color": "#333333", "weight": 2})
except:
    pass 

# 2. 加载数据
if selected_geom is not None:
    # === 局部裁剪模式 ===
    try:
        with st.spinner('正在处理数据...'):
            # 读取数据
            xds = rioxarray.open_rasterio(tif_url)
            
            # 【核心修复代码 START】
            # ArcGIS 显示正常是因为它自动过滤了 -9999。
            # 这里我们手动操作：只要小于 -10 的数值，统统变成 NaN (透明)
            # SPEI 指数不可能小于 -10，所以这很安全。
            xds = xds.where(xds > -10)
            # 【核心修复代码 END】

            # 裁剪
            clipped = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
            
            # 数据侦探：看看现在真正的最大最小值是多少
            try:
                valid_min = float(clipped.min())
                valid_max = float(clipped.max())
                st.sidebar.success(f"🔍 数据侦探 (已过滤背景):\n最小值: {valid_min:.2f}\n最大值: {valid_max:.2f}")
            except:
                pass

            # 保存并显示
            temp_file = "temp_clipped.tif"
            clipped.rio.to_raster(temp_file)
            m.add_raster(temp_file, layer_name="局部干旱等级", **vis_params)
            
            # 蓝色高亮框
            m.add_gdf(gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                      layer_name="选中区域边界", style={"fillOpacity": 0, "color": "blue", "weight": 2})
            
    except Exception as e:
        st.warning(f"无法加载数据，可能该月数据缺失或网络超时。")
else:
    # === 全图概览模式 ===
    # 注意：为了解决全图变红，全图模式也必须下载-过滤-保存，不能直接用 add_cog_layer
    try:
        with st.spinner('正在加载全区数据...'):
            xds = rioxarray.open_rasterio(tif_url)
            
            # 【核心修复】过滤背景
            xds = xds.where(xds > -10)
            
            temp_file = "temp_full.tif"
            xds.rio.to_raster(temp_file)
            m.add_raster(temp_file, layer_name="全区干旱等级", **vis_params)
    except:
         st.warning("全区数据加载超时，请尝试选择具体的盟市或旗县。")


# 尝试添加图例 (如果不报错的话)
try:
    m.add_colormap('RdBu', vmin=-3.0, vmax=3.0, label="SPEI Index")
except:
    pass

m.to_streamlit(height=650)