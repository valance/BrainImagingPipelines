import matplotlib
matplotlib.use('Agg')
import os
from scipy.ndimage import label
from nipy.labs import viz
from nibabel import load
import pylab
import matplotlib.pyplot as plt
from nipype.interfaces import fsl
import nipype.pipeline.engine as pe
import nipype.interfaces.utility as util
import nipype.interfaces.io as nio
import nipype.interfaces.freesurfer as fs
import argparse
import sys
from nipype.interfaces.io import FreeSurferSource
sys.path.insert(0,'..')
from utils import pickfirst
sys.path.insert(0,'../../utils')
from reportsink.io import ReportSink
from QA_utils import tsnr_roi


def get_coords(labels, in_file, subsess, fsdir):
    from nibabel import load
    import numpy as np
    import os 
    
    img = labels[0]
    data1 = in_file
    data,affine = load(data1).get_data(), load(data1).get_affine()
    coords = []
    labels = np.setdiff1d(np.unique(img.ravel()), [0])
    cs = []
    
    brain_dir = os.path.join(fsdir,subsess,'mri')
    lut_file='/software/Freesurfer/5.1.0/FreeSurferColorLUT.txt'
    colorfile = np.genfromtxt(lut_file,dtype='string')
    seg_file = os.path.join(brain_dir,'aparc+aseg.mgz')
    data_seg,aff_seg = load(seg_file).get_data(), load(seg_file).get_affine()
    inv_aff_seg = np.linalg.inv(aff_seg)
    
    def make_chart(coords):
        brain_loc = []
        
        for co in coords:
            realspace = np.dot(affine,np.hstack((co,1)))
            #segspace = np.dot(inv_aff_seg, np.hstack((co,1)))
            segspace = np.dot(inv_aff_seg, realspace)
            colornum = str(data_seg[segspace[0],segspace[1],segspace[2]])
            brain_loc.append(colorfile[:,1][colorfile[:,0]==colornum][0])
        
        percents = []

        for loc in np.unique(brain_loc):
            #percents.append(np.mean(loc==brain_loc, dtype=np.float64))
            percents.append(np.mean(loc==np.array(brain_loc), dtype=np.float64))
        return np.unique(brain_loc), percents
    
    for label in labels:
        cs.append(np.sum(img==label))
    
    locations = []
    percents = []
    meanval = []
    for label in labels[np.argsort(cs)[::-1]]:
        coordinates = np.asarray(np.nonzero(img==label))  
        print coordinates.shape
        locs, pers = make_chart(coordinates.T)
        i =  np.argmax(abs(data[coordinates[0,:],coordinates[1,:],coordinates[2,:]])) 
        meanval.append(np.mean(data[coordinates[0,:],coordinates[1,:],coordinates[2,:]]))
        q =  coordinates[:,i]
        locations.append(locs)
        percents.append(pers)
        coords.append(np.dot(affine, np.hstack((q,1)))[:3].tolist())  
                                 
    return [coords], [cs], locations, percents, meanval


def get_labels(in_file,thr,csize):
    from nibabel import load
    from scipy.ndimage import label
    #from numpy import *
    min_extent=csize
    data = load(in_file).get_data()
    labels, nlabels = label(abs(data)>thr)
    for idx in range(1, nlabels+1):
        if sum(sum(sum(labels==idx)))<min_extent:
            labels[labels==idx] = 0
    return [labels]
            

def show_slices(image_in, anat_file, coordinates,thr):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import pylab as pl
    import numpy as np
    from nibabel import load
    import os
    from nipy.labs import viz
    anat = anat_file
    img = image_in
    coords = coordinates[0]
    threshold=thr
    cmap=pl.cm.jet 
    prefix=None,
    show_colorbar=True
    formatter='%.2f'
    
    img1 = load(img)
    data, aff = img1.get_data(), img1.get_affine()
    anatimg = load(anat) #load('/usr/share/fsl/data/standard/MNI152_T1_1mm_brain.nii.gz')
    anatdata, anataff = anatimg.get_data(), anatimg.get_affine()
    anatdata = anatdata.astype(np.float)
    anatdata[anatdata<10.] = np.nan
    outfile1 = os.path.split(img)[1][0:-7]
    outfiles = []
    for idx,coord in enumerate(coords):
        outfile = outfile1+'cluster%02d' % idx
        osl = viz.plot_map(np.asarray(data), aff, anat=anatdata, anat_affine=anataff,
                           threshold=threshold, cmap=cmap,
                           black_bg=False, cut_coords=coord)
        if show_colorbar:
            cb = plt.colorbar(plt.gca().get_images()[1], cax=plt.axes([0.4, 0.075, 0.2, 0.025]), 
                     orientation='horizontal', format=formatter)
            cb.set_ticks([cb._values.min(), cb._values.max()])
            
        #osl.frame_axes.figure.savefig(outfile+'.svg', bbox_inches='tight', transparent=True)
        osl.frame_axes.figure.savefig(os.path.join(os.getcwd(),outfile+'.png'), dpi=600, bbox_inches='tight', transparent=True)
        #pl.savefig(os.path.join(os.getcwd(),outfile+'.png'), dpi=600, bbox_inches='tight', transparent=True)               
        outfiles.append(os.path.join(os.getcwd(),outfile+'.png'))
    return outfiles



def img_wkflw(thr, csize, name='slice_image_generator'):
    inputspec = pe.Node(util.IdentityInterface(fields=['in_file','mask_file','anat_file','reg_file', 'subject_id','fsdir']),
                        name='inputspec')
    workflow = pe.Workflow(name=name)

    applymask = pe.MapNode(interface=fsl.ApplyMask(), name='applymask',iterfield=['in_file'])
    workflow.connect(inputspec,'in_file',applymask,'in_file')
    workflow.connect(inputspec,'mask_file',applymask,'mask_file')
    
    getlabels = pe.MapNode(util.Function( input_names = ["in_file","thr","csize"], output_names =["labels"], function = get_labels), iterfield=['in_file'], name = "getlabels")
    getlabels.inputs.csize = csize
    getlabels.inputs.thr = thr
                           
    workflow.connect(applymask,'out_file',getlabels,'in_file')
    
    getcoords = pe.MapNode(util.Function(input_names=["labels","in_file",'subsess','fsdir'], output_names = ["coordinates","cs",'locations','percents','meanval'], function= get_coords), iterfield=['labels','in_file']
                          , name="get_coords")   
    
    
    workflow.connect(inputspec, 'subject_id', getcoords, 'subsess')
    workflow.connect(inputspec, 'fsdir', getcoords, 'fsdir')
    
    
    workflow.connect(getlabels,'labels', getcoords, 'labels')
    workflow.connect(applymask,'out_file',getcoords,'in_file')  
    
   
    showslices = pe.MapNode(util.Function(input_names=['image_in','anat_file','coordinates','thr'], output_names = ["outfiles"], function=show_slices), iterfield= ['image_in','coordinates'],
                            name='showslices')  
    showslices.inputs.thr = thr
    
    workflow.connect(inputspec,'anat_file',showslices,'anat_file')
    workflow.connect(getcoords,'coordinates',showslices,'coordinates') 
    workflow.connect(applymask,'out_file',showslices,'image_in')
    
    outputspec = pe.Node(util.IdentityInterface(fields=['coordinates','cs','locations','percents','meanval','imagefiles']), name='outputspec')
    workflow.connect(getcoords,'coordinates',outputspec,'coordinates')
    workflow.connect(getcoords,'cs',outputspec,'cs')
    workflow.connect(getcoords,'locations',outputspec,'locations')
    workflow.connect(getcoords,'percents',outputspec,'percents')
    workflow.connect(getcoords,'meanval',outputspec,'meanval')
    
    
    workflow.connect(showslices,'outfiles',outputspec,'imagefiles')
    
    return workflow               
    
def get_data(name='first_level_datagrab'):
    
    datasource = pe.Node(nio.DataGrabber(infields=['subject_id', 'fwhm'], outfields=['func','mask','reg','des_mat','des_mat_cov','detrended']), name='datasource')

    datasource.inputs.template = '*'
    
    datasource.inputs.base_directory = os.path.join(c.sink_dir,'analyses','func')
    
    datasource.inputs.field_template = dict(func='%s/modelfit/contrasts/fwhm_'+'%s'+'/*/*zstat*',
                                            mask = '%s/preproc/mask/'+'*.nii',
                                            reg = '%s/preproc/bbreg/*.dat',
                                            detrended = '%s/preproc/tsnr/*detrended.nii.gz',
                                            des_mat = '%s/modelfit/design/fwhm_%s/*/run?.png',
                                            des_mat_cov = '%s/modelfit/design/fwhm_%s/*/*cov.png')
    
    datasource.inputs.template_args = dict(func=[['subject_id','fwhm']],
                                           mask=[['subject_id']], 
                                           reg = [['subject_id']],
                                           detrended = [['subject_id']],
                                           des_mat = [['subject_id','fwhm']],
                                           des_mat_cov = [['subject_id','fwhm']])
    return datasource
    
def get_fx_data(name='fixedfx_level_datagrab'):
    
    datasource = pe.Node(nio.DataGrabber(infields=['subject_id', 'fwhm'], outfields=['func','mask','reg','des_mat','des_mat_cov','detrended']), name='datasource')

    datasource.inputs.template = '*'
    
    datasource.inputs.base_directory = os.path.join(c.sink_dir,'analyses','func')
    
    datasource.inputs.field_template = dict(func='%s/fixedfx/fwhm_'+'%s'+'*zstat*',
                                            mask = '%s/preproc/mask/'+'*.nii',
                                            reg = '%s/preproc/bbreg/*.dat',
                                            detrended = '%s/preproc/tsnr/*detrended.nii.gz',
                                            des_mat = '%s/modelfit/design/fwhm_%s/*/run?.png',
                                            des_mat_cov = '%s/modelfit/design/fwhm_%s/*/*cov.png')
    
    datasource.inputs.template_args = dict(func=[['subject_id','fwhm']],
                                           mask=[['subject_id']], 
                                           reg = [['subject_id']],
                                           detrended = [['subject_id']],
                                           des_mat = [['subject_id','fwhm']],
                                           des_mat_cov = [['subject_id','fwhm']])
    return datasource
    
def combine_report(thr=2.326,csize=30,fx=False):
    

    if not fx:
        workflow = pe.Workflow(name='first_level_report')
        dataflow = get_data()
    else:
        workflow = pe.Workflow(name='fixedfx_report')
        dataflow =  get_fx_data()
    
    infosource = pe.Node(util.IdentityInterface(fields=['subject_id']),
                         name='subject_names')
    infosource.iterables = ('subject_id', c.subjects)
    
    infosource1 = pe.Node(util.IdentityInterface(fields=['fwhm']),
                         name='fwhms')
    infosource1.iterables = ('fwhm', c.fwhm)
    
    fssource = pe.Node(interface = FreeSurferSource(),name='fssource')
    
    workflow.connect(infosource, 'subject_id', dataflow, 'subject_id')
    workflow.connect(infosource1, 'fwhm', dataflow, 'fwhm')
    
    workflow.connect(infosource, 'subject_id', fssource, 'subject_id')
    fssource.inputs.subjects_dir = c.surf_dir
    
    imgflow = img_wkflw(thr=thr,csize=csize)
    
    # adding cluster correction before sending to imgflow
    
    smoothest = pe.MapNode(fsl.SmoothEstimate(), name='smooth_estimate', iterfield=['zstat_file'])
    workflow.connect(dataflow,'func', smoothest, 'zstat_file')
    workflow.connect(dataflow,'mask',smoothest, 'mask_file')
    
    cluster = pe.MapNode(fsl.Cluster(), name='cluster', iterfield=['in_file','dlh','volume'])
    workflow.connect(smoothest,'dlh', cluster, 'dlh')
    workflow.connect(smoothest, 'volume', cluster, 'volume')
    cluster.inputs.connectivity = csize
    cluster.inputs.threshold = thr
    cluster.inputs.out_threshold_file = True
    workflow.connect(dataflow,'func',cluster,'in_file')
    
    workflow.connect(cluster, 'threshold_file',imgflow,'inputspec.in_file')
    #workflow.connect(dataflow,'func',imgflow, 'inputspec.in_file')
    workflow.connect(dataflow,'mask',imgflow, 'inputspec.mask_file')
    workflow.connect(dataflow,'reg',imgflow, 'inputspec.reg_file')
    
    workflow.connect(fssource,'brain',imgflow, 'inputspec.anat_file')
    
    workflow.connect(infosource, 'subject_id', imgflow, 'inputspec.subject_id')
    imgflow.inputs.inputspec.fsdir = c.surf_dir
    
    writereport = pe.Node(util.Function( input_names = ["cs","locations","percents", "in_files", "des_mat_cov","des_mat","subjects","meanval","imagefiles","surface_ims",'thr','csize','fwhm','onset_images'], output_names =["report","elements"], function = write_report), name = "writereport" )
    
    
    # add plot detrended timeseries with onsets if block
    if c.is_block_design:
        plottseries = tsnr_roi(plot=True)
        plottseries.inputs.inputspec.TR = c.TR
        workflow.connect(dataflow,'reg',plottseries, 'inputspec.reg_file')
        workflow.connect(fssource, ('aparc_aseg',pickfirst), plottseries, 'inputspec.aparc_aseg')
        workflow.connect(infosource, 'subject_id', plottseries, 'inputspec.subject')
        workflow.connect(dataflow, 'detrended', plottseries,'inputspec.tsnr_file')
        workflow.connect(infosource,('subject_id',c.subjectinfo),plottseries,'inputspec.onsets')
        workflow.connect(plottseries,'outputspec.out_file',writereport,'onset_images')
    else:
        writereport.inputs.onset_images = None
    
    
    
    #writereport = pe.Node(interface=ReportSink(),name='reportsink')
    #writereport.inputs.base_directory = os.path.join(c.sink_dir,'analyses','func')
    
    workflow.connect(infosource, 'subject_id', writereport, 'subjects')
    #workflow.connect(infosource, 'subject_id', writereport, 'container')
    workflow.connect(infosource1, 'fwhm', writereport, 'fwhm')
    
    writereport.inputs.thr = thr
    writereport.inputs.csize = csize
    
    makesurfaceplots = pe.Node(util.Function(input_names = ['con_image','reg_file','subject_id','thr','sd'], output_names = ['surface_ims', 'surface_mgzs'], function = make_surface_plots), 
                               name = 'make_surface_plots')
    
    workflow.connect(infosource, 'subject_id', makesurfaceplots, 'subject_id')
    
    makesurfaceplots.inputs.thr = thr
    makesurfaceplots.inputs.sd = c.surf_dir
    
    sinker = pe.Node(nio.DataSink(), name='sinker')
    sinker.inputs.base_directory = os.path.join(c.sink_dir,'analyses','func')
    
    workflow.connect(infosource,'subject_id',sinker,'container')
    workflow.connect(dataflow,'func',makesurfaceplots,'con_image')
    workflow.connect(dataflow,'reg',makesurfaceplots,'reg_file')
    
    workflow.connect(dataflow, 'des_mat', writereport, 'des_mat')
    workflow.connect(dataflow, 'des_mat_cov', writereport, 'des_mat_cov')
    workflow.connect(imgflow, 'outputspec.cs', writereport, 'cs')
    workflow.connect(imgflow, 'outputspec.locations', writereport, 'locations')
    workflow.connect(imgflow, 'outputspec.percents', writereport, 'percents')
    workflow.connect(imgflow, 'outputspec.meanval', writereport, 'meanval')
    workflow.connect(imgflow,'outputspec.imagefiles', writereport, 'imagefiles')
    
    workflow.connect(dataflow, 'func', writereport, 'in_files')
    workflow.connect(makesurfaceplots,'surface_ims', writereport, 'surface_ims')
    if not fx:
        workflow.connect(writereport,"report",sinker,"first_level_report")
    else:
        workflow.connect(writereport,"report",sinker,"fixed_fx_report")
    
    
    return workflow

def write_report(cs,locations,percents,in_files,
                 des_mat,des_mat_cov,subjects, meanval, 
                 imagefiles, surface_ims, thr, csize, fwhm,
                 onset_images):
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import inch
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    import reportlab
    from reportlab.platypus.flowables import PageBreak 
    import time
    from reportlab.lib.enums import TA_JUSTIFY, TA_RIGHT
    from reportlab.platypus import Image as Image2
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from numpy import array 
    from reportlab.platypus.doctemplate import NextPageTemplate, PageTemplate
    import os
    from reportlab.lib.styles import getSampleStyleSheet
    from glob import glob
    from PIL import Image
    import numpy as np
    
    def get_and_scale(imagefile,scale=1):
        from reportlab.platypus import Image as Image2
        im1 = scale_im(Image.open(imagefile))
        im = Image2(imagefile, im1.size[0]*scale, im1.size[1]*scale)  
        return im      
               
    def scale_im(im):
        # scales an image so that it will fit on the page with various margins...
        width, height = letter
        newsize = array(im.size)/(max(array(im.size)/array([width-(1*inch), height-(2*inch)])))
        newsize = tuple(map(lambda x: int(x), tuple(newsize)))
        return im.resize(newsize)      
    
     
    
    fwhm = [fwhm]
    report = os.path.join(os.getcwd(),"slice_tables.pdf")
    doc = SimpleDocTemplate(report, pagesize=letter,
                            rightMargin=36,leftMargin=36,
                            topMargin=72,bottomMargin=72)
    elements = []
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='RIGHT', alignment=TA_RIGHT))
    
    formatted_time = time.ctime()
    
    ptext = '<font size=10>%s</font>' % formatted_time     
    elements.append(Paragraph(ptext, styles["Normal"]))
    elements.append(Spacer(1, 12)) 
    
    ptext = '<font size=22>%s</font>' %('Subject '+subjects+' Report')   
    elements.append(Paragraph(ptext, styles["Normal"]))
    elements.append(Spacer(1, 24))
    
    ptext = '<font size=10>%s</font>' %("The contrast files are: ")    
    elements.append(Paragraph(ptext, styles["Normal"]))
    elements.append(Spacer(1, 12)) 
    
    contrasts = []
    for fil in in_files:
        pt = os.path.split(fil)[1]
        contrasts.append(pt) 
        ptext = '<font size=10>%s</font>' %pt   
        elements.append(Paragraph(ptext, styles["Normal"]))
        elements.append(Spacer(1, 12))     
    
    ptext = '<font size=10>%s</font>' %("The stat images were thresholded at z = %s and min cluster size = %s voxels. FWHM = %d "%(thr,csize,fwhm[0]))    
    elements.append(Paragraph(ptext, styles["Normal"]))
    elements.append(Spacer(1, 12)) 
    elements.append(PageBreak())
    
    if not isinstance(des_mat,list):
        des_mat = [des_mat]
    if not isinstance(des_mat_cov,list):
        des_mat_cov = [des_mat_cov]
    
    for i in range(len(des_mat)):
        ptext = '<font size=10>%s</font>' %('Design Matrix:')   
        elements.append(Paragraph(ptext, styles["Normal"]))
        elements.append(Spacer(1, 12))
        im = get_and_scale(des_mat[i],.6)
        elements.append(im)    
        elements.append(Spacer(1, 12))  
    
        ptext = '<font size=10>%s</font>' %('Covariance Matrix:')   
        elements.append(Paragraph(ptext, styles["Normal"]))
        elements.append(Spacer(1, 12))
        im = get_and_scale(des_mat_cov[i],.6)
        elements.append(im)    
        elements.append(PageBreak())
    
    if onset_images:
        for image in onset_images:
            if isinstance(image,list):
                for im0 in image:
                    im = get_and_scale(im0)
                    elements.append(im)
            else:
                im = get_and_scale(image)
                elements.append(im)
                
    
    for i, con_cs in enumerate(cs):
        data = [['Size','Location','Ratio','Mean(z)','Image']]
        for j, cluster in enumerate(con_cs[0]):
            data.append([])
            data[j+1].append(cluster)
            locstr = ''
            perstr = ''
            if len(locations[i][j]) <= 50:
                for k, loc in enumerate(locations[i][j]):
                    locstr = locstr + loc + '\n'
                    perstr = perstr+'%.2f\n'%percents[i][j][k]
                    
            data[j+1].append(locstr)
            data[j+1].append(perstr)
            meanstr = '%2.2f'%meanval[i][j]
            data[j+1].append(meanstr)
            im = get_and_scale(imagefiles[i][j],.5)
            data[j+1].append(im)
        
        print data
        t=Table(data)
        t.setStyle(TableStyle([('ALIGN',(0,0), (-1,-1),'LEFT'),
                               ('VALIGN',(0,0), (-1,-1), 'TOP'),
                               ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
                               ('BOX', (0,0), (-1,-1), 0.25, colors.black)]))
        t.hAlign='LEFT'
        ptext = '<font size=10>%s</font>' %('Contrast:  %s'%(contrasts[i]))   
        elements.append(Paragraph(ptext,styles["Normal"]))
        elements.append(Spacer(1, 12))
        elements.append(get_and_scale(surface_ims[i]))
        elements.append(Spacer(1, 12))
        elements.append(t)
        elements.append(Spacer(1, 12))
        #elements.append(PageBreak())
    
    doc.build(elements)
    return report, elements 

def make_surface_plots(con_image,reg_file,subject_id,thr,sd):  
    import matplotlib
    matplotlib.use('Agg')
    #from surfer import Brain
    import os
    from glob import glob
        
    def make_image(zstat_path,bbreg_path):
        name_path = os.path.join(os.getcwd(),os.path.split(zstat_path)[1]+'_reg_surface.mgh')
        systemcommand ='mri_vol2surf --mov %s --reg %s --hemi lh --projfrac-max 0 1 0.1 --o %s --out_type mgh --sd %s'%(zstat_path,bbreg_path,name_path, sd)
        print systemcommand
        os.system(systemcommand)
        return name_path
        
    def make_brain(subject_id,image_path):
        from mayavi import mlab
        from surfer import Brain
        hemi = 'lh'
        surface = 'inflated'
        overlay = image_path 
        brain = Brain(subject_id, hemi, surface)
        brain.add_overlay(image_path,min=thr)
        outpath = os.path.join(os.getcwd(),os.path.split(image_path)[1]+'_surf.png')
        brain.save_montage(outpath)
        return outpath
            
    surface_ims = []
    surface_mgzs = []
    for con in con_image:
        surf_mgz = make_image(format(con),reg_file)
        surface_mgzs.append(surf_mgz)
        surface_ims.append(make_brain(subject_id,surf_mgz))
                            
    return surface_ims, surface_mgzs   
  
  
  
  
if __name__ == '__main__':

    parser = argparse.ArgumentParser(description="example: \
                        run resting_preproc.py -c config.py")
    parser.add_argument('-c','--config',
                        dest='config',
                        required=True,
                        help='location of config file'
                        )
    parser.add_argument('-fx','--fixedfx',
                        dest='fx',
                        required=False,
                        help='whether to write fixedfx report'
                        )
    args = parser.parse_args()
    path, fname = os.path.split(os.path.realpath(args.config))
    sys.path.append(path)
    c = __import__(fname.split('.')[0])

    workflow = combine_report(fx=args.fx)
    workflow.base_dir = c.working_dir
    

    if not os.environ['SUBJECTS_DIR'] == c.surf_dir:
        print "Your SUBJECTS_DIR is incorrect!"
        print "export SUBJECTS_DIR=%s"%c.surf_dir
        
    else:
        if c.run_on_grid:
            workflow.run(plugin=c.plugin, plugin_args=c.plugin_args['qsub_args']+'-X')
        else:
            workflow.run()
        
