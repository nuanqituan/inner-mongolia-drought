import streamlit as st
import leafmap.foliumap as leafmap
import geopandas as gpd
import rioxarray
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
# 例如: USER_NAME = "nuanqituan"
USER_NAME = "nuanqituan" 
REPO_NAME = "inner-mongolia-drought"

# 自动生成数据仓库地址
REPO_URL = f"https://raw.githubusercontent.com/{USER_NAME}/{REPO_NAME}/main/data"

# 你的三个核心矢量文件
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
    st.error(f"❌ 数据加载失败！请检查 GitHub 用户名 '{USER_NAME}' 是否正确，且仓库是 Public 公开状态。")
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
    
    # 筛选旗县 (使用 ParentCity 字段)
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
vis_params = {'min': -2.5, 'max': 2.5, 'palette': 'RdBu'}

# 1. 显示内蒙古轮廓
try:
    m.add_geojson(BOUNDARY_URL, layer_name="内蒙古轮廓", style={"fillOpacity": 0, "color": "#333333", "weight": 2})
except:
    pass 

# 2. 加载数据 (修复全红问题的关键部分)
if selected_geom is not None:
    try:
        with st.spinner('正在读取数据...'):
            # 【关键修复】masked=True 会自动把无效值(-9999)变成透明
            xds = rioxarray.open_rasterio(tif_url, masked=True)
            
            # --- 数据侦探：在左侧显示当前数据的最大最小值，帮你判断数据是否正常 ---
            try:
                valid_min = float(xds.min())
                valid_max = float(xds.max())
                st.sidebar.info(f"🔍 数据侦探:\n当前区域最小值: {valid_min:.2f}\n当前区域最大值: {valid_max:.2f}")
            except:
                st.sidebar.warning("数据全为空，可能是该月份没有数据")

            # 裁剪并显示
            clipped = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
            temp_file = "temp_clipped.tif"
            clipped.rio.to_raster(temp_file)
            m.add_raster(temp_file, layer_name="局部干旱等级", **vis_params)
            
            # 蓝色高亮框
            m.add_gdf(gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                      layer_name="选中区域边界", style={"fillOpacity": 0, "color": "blue", "weight": 2})
            
    except Exception as e:
        st.warning(f"⚠️ 无法加载该区域数据 (可能是该年份数据缺失)。")
else:
    # 全图模式
    # 这里我们不用 clipped，直接加载，但可能无法自动 mask，建议主要查看局部
    m.add_cog_layer(tif_url, name="全区数据", **vis_params)

# 【临时禁用图例条，防止报错】
# m.add_colormap('RdBu', vmin=-2.5, vmax=2.5, label="SPEI Index")

m.to_streamlit(height=650)
