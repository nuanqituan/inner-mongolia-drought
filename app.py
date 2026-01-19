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
# 2. 数据连接配置 (最关键的一步)
# ==========================================
# ！！！请在这里填入你的 GitHub 用户名！！！
# 例如: USER_NAME = "gel1988918"
USER_NAME = "nuanqituan" 
REPO_NAME = "inner-mongolia-drought"

# 自动生成数据仓库地址
REPO_URL = f"https://raw.githubusercontent.com/{USER_NAME}/{REPO_NAME}/main/data"

# 你的三个核心矢量文件 (完全对应你的截图文件名)
LEAGUE_URL = f"{REPO_URL}/inner_mongolia_city.json"      # 盟市文件
BANNER_URL = f"{REPO_URL}/inner_mongolia_banners.json"   # 旗县文件
BOUNDARY_URL = f"{REPO_URL}/inner_mongolia_boundary.json" # 整体边界

@st.cache_data
def load_data():
    try:
        # 读取 GitHub 上的数据
        leagues_gdf = gpd.read_file(LEAGUE_URL)
        banners_gdf = gpd.read_file(BANNER_URL)
        return leagues_gdf, banners_gdf
    except Exception as e:
        return None, None

# 加载数据
leagues_gdf, banners_gdf = load_data()

# 如果加载失败，给出一个红色的报错提示
if leagues_gdf is None or banners_gdf is None:
    st.error(f"❌ 数据加载失败！\n请检查 app.py 第17行，你的用户名 '{USER_NAME}' 写对了吗？\n如果是私有仓库，请去 GitHub 设置为 Public。")
    st.stop()

# ==========================================
# 3. 左侧控制面板
# ==========================================
st.sidebar.header("ðﾟﾕﾹ️ 参数选择")

# --- A. 区域选择 (级联逻辑) ---
# 1. 获取盟市列表 (按照你的截图，字段名是 'name')
league_names = sorted(leagues_gdf['name'].unique())
selected_league = st.sidebar.selectbox("ðﾟﾓﾍ 选择盟市", ["全区概览"] + list(league_names))

selected_geom = None
zoom_level = 5
center = [44.0, 115.0] # 内蒙古中心点

if selected_league != "全区概览":
    # 选了盟市，提取该盟市的形状
    league_feature = leagues_gdf[leagues_gdf['name'] == selected_league]
    selected_geom = league_feature.unary_union
    
    # 2. 筛选旗县：使用你截图中的 'ParentCity' 字段
    # 【注意】这里严格对应你截图里的字段名，一个字母都不能错
    filtered_banners = banners_gdf[banners_gdf['ParentCity'] == selected_league]
    banner_names = sorted(filtered_banners['name'].unique())
    
    selected_banner = st.sidebar.selectbox("ðﾟﾚﾩ 选择旗县 (可选)", ["全盟市"] + list(banner_names))
    
    if selected_banner != "全盟市":
        # 选了具体旗县
        target_feature = filtered_banners[filtered_banners['name'] == selected_banner]
        if not target_feature.empty:
            selected_geom = target_feature.geometry.iloc[0]
            # 自动定位并放大
            centroid = target_feature.geometry.centroid
            center = [centroid.y.values[0], centroid.x.values[0]]
            zoom_level = 8
    else:
        # 只选了盟市
        centroid = league_feature.geometry.centroid
        center = [centroid.y.values[0], centroid.x.values[0]]
        zoom_level = 6

# --- B. 时间选择 ---
st.sidebar.markdown("---")
scale_display = st.sidebar.selectbox("ðﾟﾓﾊ SPEI 尺度", ["1个月 (气象干旱)", "3个月 (农业干旱)", "12个月 (水文干旱)"])
scale_map = {"1个月 (气象干旱)": "01", "3个月 (农业干旱)": "03", "12个月 (水文干旱)": "12"}
sel_scale = scale_map[scale_display]

sel_year = st.sidebar.slider("ðﾟﾓﾅ 年份", 1950, 2025, 2024)
sel_month = st.sidebar.select_slider("ðﾟﾗﾓ️ 月份", range(1, 13), 8)

# 构造 TIFF 文件链接 (文件名格式必须是: SPEI_01_2024_08.tif)
month_str = f"{sel_month:02d}"
tif_url = f"{REPO_URL}/SPEI_{sel_scale}_{sel_year}_{month_str}.tif"

# ==========================================
# 4. 地图展示
# ==========================================
st.subheader(f"分析视图: {selected_league} - {sel_year}年{sel_month}月")

m = leafmap.Map(center=center, zoom=zoom_level)
vis_params = {'min': -2.5, 'max': 2.5, 'palette': 'RdBu'}

# 1. 始终显示内蒙古整体轮廓 (黑色边框)
try:
    m.add_geojson(
        BOUNDARY_URL, 
        layer_name="内蒙古轮廓", 
        style={"fillOpacity": 0, "color": "#333333", "weight": 2}
    )
except:
    pass 

# 2. 加载干旱数据 (尝试裁剪)
if selected_geom is not None:
    try:
        with st.spinner('正在计算区域裁剪...'):
            # 读取并裁剪
            xds = rioxarray.open_rasterio(tif_url)
            clipped = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
            
            # 保存临时文件并展示
            temp_file = "temp_clipped.tif"
            clipped.rio.to_raster(temp_file)
            m.add_raster(temp_file, layer_name="局部干旱等级", **vis_params)
            
            # 给选中区域加个蓝色高亮框
            m.add_gdf(gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                      layer_name="选中区域边界", 
                      style={"fillOpacity": 0, "color": "blue", "weight": 2})
            
    except Exception as e:
        # 如果裁剪失败(通常是网络原因)，显示全图保底
        st.warning("⚠️ 网络加载稍慢，已切换为全区显示。")
        m.add_cog_layer(tif_url, name="全区数据", **vis_params)
else:
    # 默认显示全图
    m.add_cog_layer(tif_url, name="全区数据", **vis_params)

# 添加图例
# m.add_colormap('RdBu', vmin=-2.5, vmax=2.5, label="SPEI Index")
m.to_streamlit(height=650)
