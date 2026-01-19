import streamlit as st
import leafmap.foliumap as leafmap
import geopandas as gpd
import rioxarray
import xarray as xr
import os
import numpy as np

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
# 4. 地图展示核心逻辑 (使用原始代码的正确方法)
# ==========================================
st.subheader(f"分析视图: {selected_league} - {sel_year}年{sel_month}月")

# 可视化参数
vis_params = {
    'min': -3, 
    'max': 3, 
    'palette': 'RdBu'  # 红=干旱, 蓝=湿润
}

# 创建地图
m = leafmap.Map(center=center, zoom=zoom_level)

# 1. 始终显示内蒙古轮廓
try:
    m.add_geojson(
        BOUNDARY_PATH, 
        layer_name="内蒙古轮廓", 
        style={"fillOpacity": 0, "color": "#333333", "weight": 2}
    )
except: 
    pass

# 2. 加载SPEI数据
if not os.path.exists(tif_file):
    st.warning(f"⚠️ 暂无该月份数据: {tif_file}")
else:
    try:
        # === 方法A: 如果选择了区域,进行裁剪 ===
        if selected_geom is not None:
            with st.spinner('📊 正在处理区域数据...'):
                # 读取并裁剪
                xds = rioxarray.open_rasterio(tif_file)
                
                # 数据统计(裁剪前)
                data_before = xds.values[0]
                valid_before = data_before[(data_before > -10) & (~np.isnan(data_before))]
                st.sidebar.info(f"🗺️ 原始数据: {len(valid_before)} 像素")
                
                # 裁剪到选中区域
                clipped = xds.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
                
                # 数据统计(裁剪后)
                data_after = clipped.values[0]
                valid_after = data_after[(data_after > -10) & (~np.isnan(data_after))]
                
                if len(valid_after) == 0:
                    st.error("❌ 该区域当前时段无有效数据!")
                else:
                    st.sidebar.success(f"✂️ 裁剪后: {len(valid_after)} 像素")
                    st.sidebar.info(f"📈 SPEI范围: {np.min(valid_after):.2f} ~ {np.max(valid_after):.2f}")
                    
                    # 保存临时文件
                    temp_file = "temp_clipped.tif"
                    clipped.rio.to_raster(temp_file)
                    
                    # 使用 leafmap 的 add_raster 方法 (关键!)
                    m.add_raster(
                        temp_file, 
                        layer_name="SPEI干旱指数",
                        colormap='RdBu',
                        vmin=-3,
                        vmax=3
                    )
                    
                    # 清理临时文件
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                    
                    # 添加选中区域边框
                    m.add_gdf(
                        gpd.GeoDataFrame(geometry=[selected_geom], crs="EPSG:4326"), 
                        layer_name="选中区域边界", 
                        style={"fillOpacity": 0, "color": "#0066ff", "weight": 3}
                    )
                    
                    st.success("✅ 区域数据加载成功!")
        
        # === 方法B: 全区显示 ===
        else:
            # 数据统计
            xds = rioxarray.open_rasterio(tif_file)
            data = xds.values[0]
            valid_data = data[(data > -10) & (~np.isnan(data))]
            
            if len(valid_data) > 0:
                st.sidebar.success(f"✅ 有效像素: {len(valid_data)}")
                st.sidebar.info(f"📊 SPEI范围: {np.min(valid_data):.2f} ~ {np.max(valid_data):.2f}")
            
            # 直接使用 add_raster 显示全图
            m.add_raster(
                tif_file,
                layer_name="SPEI干旱指数",
                colormap='RdBu',
                vmin=-3,
                vmax=3
            )
            
            st.success("✅ 全区数据加载成功!")
        
        # 添加图例
        m.add_colormap(
            cmap='RdBu',
            vmin=-3,
            vmax=3,
            label="SPEI干旱指数"
        )
        
        # 添加自定义图例说明
        legend_dict = {
            '极端湿润 (>2)': '#0571b0',
            '严重湿润 (1.5~2)': '#92c5de',
            '中度湿润 (1~1.5)': '#d1e5f0',
            '正常 (-1~1)': '#f7f7f7',
            '中度干旱 (-1.5~-1)': '#fddbc7',
            '严重干旱 (-2~-1.5)': '#f4a582',
            '极端干旱 (<-2)': '#ca0020'
        }
        try:
            m.add_legend(title="干旱等级", legend_dict=legend_dict, position='bottomright')
        except:
            pass
            
    except Exception as e:
        st.error(f"❌ 数据加载失败: {e}")
        import traceback
        with st.expander("🔍 查看详细错误"):
            st.code(traceback.format_exc())

# 显示地图
m.to_streamlit(height=650)

# ==========================================
# 5. 统计信息面板
# ==========================================
if os.path.exists(tif_file):
    st.markdown("---")
    st.markdown("### 📊 统计信息")
    
    try:
        # 读取数据
        xds_stats = rioxarray.open_rasterio(tif_file)
        
        # 如果选了区域就裁剪
        if selected_geom is not None:
            xds_stats = xds_stats.rio.clip([selected_geom], crs="EPSG:4326", drop=True)
        
        # 数据处理
        data_stats = xds_stats.values[0]
        data_stats = np.where(data_stats > -10, data_stats, np.nan)
        valid = data_stats[~np.isnan(data_stats)]
        
        if len(valid) > 0:
            # 基础统计
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("最小值", f"{np.min(valid):.2f}")
            col2.metric("平均值", f"{np.mean(valid):.2f}")
            col3.metric("最大值", f"{np.max(valid):.2f}")
            col4.metric("有效像素", f"{len(valid)}")
            
            # 干旱等级统计
            extreme_drought = np.sum(valid < -2)
            severe_drought = np.sum((valid >= -2) & (valid < -1.5))
            moderate_drought = np.sum((valid >= -1.5) & (valid < -1))
            normal = np.sum((valid >= -1) & (valid <= 1))
            wet = np.sum(valid > 1)
            
            st.markdown("### 🌵 干旱等级分布")
            
            col_a, col_b, col_c, col_d, col_e = st.columns(5)
            col_a.metric("极端干旱", f"{100*extreme_drought/len(valid):.1f}%")
            col_b.metric("严重干旱", f"{100*severe_drought/len(valid):.1f}%")
            col_c.metric("中度干旱", f"{100*moderate_drought/len(valid):.1f}%")
            col_d.metric("正常", f"{100*normal/len(valid):.1f}%")
            col_e.metric("湿润", f"{100*wet/len(valid):.1f}%")
            
            # 可视化分布
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(10, 3))
            
            categories = ['极端干旱', '严重干旱', '中度干旱', '正常', '湿润']
            values = [extreme_drought, severe_drought, moderate_drought, normal, wet]
            colors = ['#ca0020', '#f4a582', '#fddbc7', '#f7f7f7', '#0571b0']
            
            ax.barh(categories, values, color=colors)
            ax.set_xlabel('像素数量')
            ax.set_title('干旱等级分布')
            
            st.pyplot(fig)
            
    except Exception as e:
        st.info("统计信息计算中...")