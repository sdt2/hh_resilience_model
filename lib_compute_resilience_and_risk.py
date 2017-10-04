#modified version from lib_compute_resilience_and_risk_financing.py
import matplotlib
matplotlib.use('AGG')

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pandas_helper import get_list_of_index_names, broadcast_simple, concat_categories
from scipy.interpolate import interp1d
from lib_gather_data import social_to_tx_and_gsp
import math

from lib_country_dir import *

import seaborn as sns

sns_pal = sns.color_palette('Set1', n_colors=8, desat=.5)
q_colors = [sns_pal[0],sns_pal[1],sns_pal[2],sns_pal[3],sns_pal[5]]

def get_weighted_mean(q1,q2,q3,q4,q5,key,weight_key='pcwgt'):
    
    if q1.shape[0] > 0:
        my_ret = [np.average(q1[key], weights=q1[weight_key])]
    else: my_ret = [0]
    
    if q2.shape[0] > 0:
        my_ret.append(np.average(q2[key], weights=q2[weight_key]))
    else: my_ret.append(0)

    if q3.shape[0] > 0:
        my_ret.append(np.average(q3[key], weights=q3[weight_key]))
    else: my_ret.append(0)

    if q4.shape[0] > 0:
        my_ret.append(np.average(q4[key], weights=q4[weight_key]))
    else: my_ret.append(0)

    if q5.shape[0] > 0:
        my_ret.append(np.average(q5[key], weights=q5[weight_key]))
    else: my_ret.append(0)    

    return my_ret

def get_weighted_median(q1,q2,q3,q4,q5,key):
    
    q1.sort_values(key, inplace=True)
    q2.sort_values(key, inplace=True)
    q3.sort_values(key, inplace=True)
    q4.sort_values(key, inplace=True)
    q5.sort_values(key, inplace=True)

    cumsum = q1.pcwgt.cumsum()
    cutoff = q1.pcwgt.sum() / 2.0
    median_q1 = round(q1[key][cumsum >= cutoff].iloc[0],3)

    cumsum = q2.pcwgt.cumsum()
    cutoff = q2.pcwgt.sum() / 2.0
    median_q2 = round(q2[key][cumsum >= cutoff].iloc[0],3)

    cumsum = q3.pcwgt.cumsum()
    cutoff = q3.pcwgt.sum() / 2.0
    median_q3 = round(q3[key][cumsum >= cutoff].iloc[0],3)

    cumsum = q4.pcwgt.cumsum()
    cutoff = q4.pcwgt.sum() / 2.0
    median_q4 = round(q4[key][cumsum >= cutoff].iloc[0],3)

    cumsum = q5.pcwgt.cumsum()
    cutoff = q5.pcwgt.sum() / 2.0
    median_q5 = round(q5[key][cumsum >= cutoff].iloc[0],3)

    return [median_q1,median_q2,median_q3,median_q4,median_q5]

def apply_policies(pol_str,macro,cat_info,hazard_ratios):
    
    # POLICY: Reduce vulnerability of the poor by 5% of their current exposure
    if pol_str == '_exp095':
        print('--> POLICY('+pol_str+'): Reducing vulnerability of the poor by 5%!')

        cat_info.loc[cat_info.ispoor==1,'v']*=0.95 
    
    # POLICY: Reduce vulnerability of the rich by 5% of their current exposure    
    elif pol_str == '_exr095':
        print('--> POLICY('+pol_str+'): Reducing vulnerability of the rich by 5%!')

        cat_info.loc[cat_info.ispoor==0,'v']*=0.95 
        
    # POLICY: Increase income of the poor by 10%
    elif pol_str == '_pcinc_p_110':
        print('--> POLICY('+pol_str+'): Increase income of the poor by 10%')
        
        cat_info.loc[cat_info.ispoor==1,'c'] *= 1.10
        cat_info.loc[cat_info.ispoor==1,'pcinc'] *= 1.10
        cat_info.loc[cat_info.ispoor==1,'pcinc_ae'] *= 1.10

        cat_info['social'] = cat_info['social']/cat_info['pcinc']

    # POLICY: Increase social transfers to poor BY one third
    elif pol_str == '_soc133':
        print('--> POLICY('+pol_str+'): Increase social transfers to poor BY one third')

        # Cost of this policy = sum(social_topup), per person
        cat_info['social_topup'] = 0
        cat_info.loc[cat_info.ispoor==1,'social_topup'] = 0.333*cat_info.loc[cat_info.ispoor==1,['social','c']].prod(axis=1)

        cat_info.loc[cat_info.ispoor==1,'c']*=(1.0+0.333*cat_info.loc[cat_info.ispoor==1,'social'])
        cat_info.loc[cat_info.ispoor==1,'pcinc']*=(1.0+0.333*cat_info.loc[cat_info.ispoor==1,'social'])
        cat_info.loc[cat_info.ispoor==1,'pcinc_ae']*=(1.0+0.333*cat_info.loc[cat_info.ispoor==1,'social'])

        cat_info['social'] = (cat_info['social_topup']+cat_info['pcsoc'])/cat_info['pcinc']

    # POLICY: Decrease reconstruction time by 1/3
    elif pol_str == '_rec067':
        print('--> POLICY('+pol_str+'): Decrease reconstruction time by 1/3')
        macro['T_rebuild_K'] *= 0.666667


    # POLICY: Increase access to early warnings to 100%
    elif pol_str == '_ew100':
        print('--> POLICY('+pol_str+'): Increase access to early warnings to 100%')
        cat_info['shew'] = 1.0

    # POLICY: Decrease vulnerability of poor by 30%
    elif pol_str == '_vul070':
        print('--> POLICY('+pol_str+'): Decrease vulnerability of poor by 30%')

        cat_info.loc[cat_info.ispoor==1,'v']*=0.70

    # POLICY: Decrease vulnerability of rich by 30%
    elif pol_str == '_vul070r':
        print('--> POLICY('+pol_str+'): Decrease vulnerability of poor by 30%')
        
        cat_info.loc[cat_info.ispoor==0,'v']*=0.70

    elif pol_str == '_noPT': pass

    elif pol_str != '':
        print('What is this? --> ',pol_str)
        assert(False)

    return macro,cat_info,hazard_ratios

def compute_with_hazard_ratios(myCountry,pol_str,fname,macro,cat_info,economy,event_level,income_cats,default_rp,rm_overlap,verbose_replace=True):

    #cat_info = cat_info[cat_info.c>0]
    hazard_ratios = pd.read_csv(fname, index_col=event_level+[income_cats])

    macro,cat_info,hazard_ratios = apply_policies(pol_str,macro,cat_info,hazard_ratios)

    #compute
    return process_input(myCountry,pol_str,macro,cat_info,hazard_ratios,economy,event_level,default_rp,rm_overlap,verbose_replace=True)

def process_input(myCountry,pol_str,macro,cat_info,hazard_ratios,economy,event_level,default_rp,rm_overlap,verbose_replace=True):
    flag1=False
    flag2=False

    if type(hazard_ratios)==pd.DataFrame:
        
        hazard_ratios = hazard_ratios.reset_index().set_index(economy).dropna()
        if 'Unnamed: 0' in hazard_ratios.columns: hazard_ratios = hazard_ratios.drop('Unnamed: 0',axis=1)
        
        #These lines remove countries in macro not in cat_info
        if myCountry == 'SL': hazard_ratios = hazard_ratios.dropna()
        else: hazard_ratios = hazard_ratios.fillna(0)
            
        common_places = [c for c in macro.index if c in cat_info.index and c in hazard_ratios.index]
        #print(common_places)

        hazard_ratios = hazard_ratios.reset_index().set_index(event_level+['hhid'])

        # This drops 1 province from macro
        macro = macro.ix[common_places]

        # Nothing drops from cat_info
        cat_info = cat_info.ix[common_places]

        # Nothing drops from hazard_ratios
        hazard_ratios = hazard_ratios.ix[common_places]

        if hazard_ratios.empty:
            hazard_ratios=None
			
    if hazard_ratios is None:
        hazard_ratios = pd.Series(1,index=pd.MultiIndex.from_product([macro.index,'default_hazard'],names=[economy, 'hazard']))
		
    #if hazard data has no hazard, it is broadcasted to default hazard
    if 'hazard' not in get_list_of_index_names(hazard_ratios):
        print('Should not be here: hazard not in \'hazard_ratios\'')
        hazard_ratios = broadcast_simple(hazard_ratios, pd.Index(['default_hazard'], name='hazard'))     
		
    #if hazard data has no rp, it is broadcasted to default rp
    if 'rp' not in get_list_of_index_names(hazard_ratios):
        print('Should not be here: RP not in \'hazard_ratios\'')
        hazard_ratios_event = broadcast_simple(hazard_ratios, pd.Index([default_rp], name='rp'))

    # Interpolates data to a more granular grid for return periods that includes all protection values that are potentially not the same in hazard_ratios.
    else:
        hazard_ratios_event = pd.DataFrame()
        for haz in hazard_ratios.reset_index().hazard.unique():
            hazard_ratios_event = hazard_ratios_event.append(interpolate_rps(hazard_ratios.reset_index().ix[hazard_ratios.reset_index().hazard==haz,:].set_index(hazard_ratios.index.names), macro.protection,option=default_rp))
            
        hazard_ratios_event = same_rps_all_hazards(hazard_ratios_event)

    # Now that we have the same set of return periods, remove overlap of losses between PCRAFI and SSBN
    if myCountry == 'FJ' and rm_overlap == True:
        hazard_ratios_event = hazard_ratios_event.reset_index().set_index(['Division','rp','hhid'])
        hazard_ratios_event.loc[hazard_ratios_event.hazard=='flood_fluv_undef','fa'] -= 0.4*hazard_ratios_event.loc[hazard_ratios_event.hazard=='TC','fa']*(hazard_ratios_event.loc[hazard_ratios_event.hazard=='flood_fluv_undef','fa']/(hazard_ratios_event.loc[hazard_ratios_event.hazard=='flood_fluv_undef','fa']+hazard_ratios_event.loc[hazard_ratios_event.hazard=='flood_pluv','fa']))
        hazard_ratios_event.loc[hazard_ratios_event.hazard=='flood_pluv','fa'] -= 0.4*hazard_ratios_event.loc[hazard_ratios_event.hazard=='TC','fa']*(hazard_ratios_event.loc[hazard_ratios_event.hazard=='flood_pluv','fa']/(hazard_ratios_event.loc[hazard_ratios_event.hazard=='flood_fluv_undef','fa']+hazard_ratios_event.loc[hazard_ratios_event.hazard=='flood_pluv','fa']))
        hazard_ratios_event['fa'] = hazard_ratios_event['fa'].clip(lower=0.0)
        
        hazard_ratios_event = hazard_ratios_event.reset_index().set_index(['Division','hazard','rp','hhid'])

    # PSA input: original value of c
    avg_c = round(np.average(macro['gdp_pc_pp_prov'],weights=macro['pop'])/get_to_USD(myCountry),2)
    print('\nMean consumption (PSA): ',avg_c,' USD.\nMean GDP pc ',round(np.average(macro['gdp_pc_pp_prov'],weights=macro['pop'])/get_to_USD(myCountry),2),' USD.\n')

    cat_info['protection']=broadcast_simple(macro['protection'],cat_info.index)	

    ##add finance to diversification and taxation
    cat_info['social'] = unpack_social(macro,cat_info)

    ##cat_info['social']+= 0.1* cat_info['axfin']
    macro['tau_tax'], cat_info['gamma_SP'] = social_to_tx_and_gsp(economy,cat_info)
            
    #RECompute consumption from k and new gamma_SP and tau_tax
    cat_info['c'] = macro['avg_prod_k']*(1.-macro['tau_tax'])*cat_info['k']/(1.-cat_info['social'])
    # ^ this is per individual

    print('all weights ',cat_info['pcwgt'].sum())

    #plt.cla()
    #ax = plt.gca()
    #ci_heights, ci_bins = np.histogram(cat_info.c.clip(upper=50000),bins=50, weights=cat_info.pcwgt)
    #plt.gca().bar(ci_bins[:-1], ci_heights, width=ci_bins[1]-ci_bins[0], facecolor=q_colors[1], label='C2',alpha=0.4)
    #plt.legend()
    #fig = ax.get_figure()
    #fig.savefig('/Users/brian/Desktop/my_plots/'+myCountry+pol_str+'_consumption_init.pdf',format='pdf')

    print('Re-recalc mean cons (pc)',round(np.average((cat_info['c']*cat_info['pcwgt']).sum(level=economy)/macro['pop'],weights=macro['pop']),2),'(local curr).\n')    


    ####FORMATTING
    #gets the event level index
    event_level_index = hazard_ratios_event.reset_index().set_index(event_level).index #index composed on countries, hazards and rps.

    #Broadcast macro to event level 
    macro_event = broadcast_simple(macro,event_level_index)	
    #rebuilding exponentially to 95% of initial stock in reconst_duration
    recons_rate = np.log(1/0.05) / macro_event['T_rebuild_K']  

    #Calculation of macroeconomic resilience
    macro_event['macro_multiplier'] =(hazard_ratios_event['dy_over_dk'].mean(level=event_level)+recons_rate)/(macro_event['rho']+recons_rate)  #Gamma in the technical paper
    
    #updates columns in macro with columns in hazard_ratios_event
    cols = [c for c in macro_event if c in hazard_ratios_event] #columns that are both in macro_event and hazard_ratios_event
    if not cols==[]:
        if verbose_replace:
            flag1=True
            print('Replaced in macro: '+', '.join(cols))
            macro_event[cols] =  hazard_ratios_event[cols]
    
    #Broadcast categories to event level
    cats_event = broadcast_simple(cat_info,  event_level_index)
    cats_event['public_loss_v'] = hazard_ratios_event.public_loss_v


    #updates columns in cats with columns in hazard_ratios_event	
    # applies mh ratios to relevant columns
    cols_c = [c for c in cats_event if c in hazard_ratios_event] #columns that are both in cats_event and hazard_ratios_event    
    if not cols_c==[]:
        hrb = broadcast_simple(hazard_ratios_event[cols_c], cat_info.index).reset_index().set_index(get_list_of_index_names(cats_event)) #explicitly broadcasts hazard ratios to contain income categories
        cats_event[cols_c] = hrb
        if verbose_replace:
            flag2=True
            print('Replaced in cats: '+', '.join(cols_c))
    if (flag1 and flag2):
        print('Replaced in both: '+', '.join(np.intersect1d(cols,cols_c)))

    return macro_event, cats_event, hazard_ratios_event 

def compute_dK(pol_str,macro_event, cats_event,event_level,affected_cats,share_public_assets=False,is_local_welfare=False,is_revised_dw=True):

    cats_event_ia=concat_categories(cats_event,cats_event,index= affected_cats)
    
    #counts affected and non affected
    print('From here: weights (pc and hh) = nAffected and nNotAffected hh/ind') 

    cats_event['fa'] = cats_event.fa.fillna(1E-8)
    
    for aWGT in ['hhwgt','pcwgt','pcwgt_ae']:
        myNaf = cats_event[aWGT]*cats_event.fa
        myNna = cats_event[aWGT]*(1-cats_event.fa)
        cats_event_ia[aWGT] = concat_categories(myNaf,myNna, index= affected_cats)    
        #print('From here: \'weight\' = nAffected and nNotAffected: individuals') 
        
    #de_index so can access cats as columns and index is still event
    cats_event_ia = cats_event_ia.reset_index(['hhid', 'affected_cat']).sort_index()

    #actual vulnerability
    cats_event_ia['v_shew']=cats_event_ia['v']*(1-macro_event['pi']*cats_event_ia['shew']) 

    #capital losses and total capital losses. Each household's capital losses is the sum of their private losses and public infrastructure losses (in proportion to their capital)
    cats_event_ia['dk'] = cats_event_ia[['hh_share','k','v_shew']].prod(axis=1, skipna=False)+cats_event_ia[['k','public_loss_v']].prod(axis=1, skipna=False)
    cats_event_ia.ix[(cats_event_ia.affected_cat=='na'), 'dk']=0

    #'provincial' losses
    # dk_event is WHEN the event happens--doesn't yet include RP/probability
    macro_event['dk_event']   =  cats_event_ia[['dk','pcwgt']].prod(axis=1,skipna=False).sum(level=event_level)
 
    #immediate consumption losses: direct capital losses plus losses through event-scale depression of transfers
    if not share_public_assets:
        print('\nInfra & public asset costs are assigned to *each hh*\n')
        cats_event_ia['dc'] = (1-macro_event['tau_tax'])*cats_event_ia['dk'] + cats_event_ia['gamma_SP']*macro_event[['tau_tax','dk_event']].prod(axis=1)
        public_costs = None

    else:
        print('\nSharing infra & public asset costs among all households *nationally*\n')
        cats_event_ia = cats_event_ia.reset_index().set_index(event_level+['hhid','affected_cat'])
        rebuild_fees = pd.DataFrame(cats_event_ia[['k','dk','pcwgt']],index=cats_event_ia.index)

        cats_event_ia = cats_event_ia.reset_index().set_index(event_level)
        rebuild_fees = rebuild_fees.reset_index().set_index(event_level)

        rebuild_fees['dk_public'] = cats_event_ia[['public_loss_v','k']].prod(axis=1,skipna=False) 
        rebuild_fees.loc[rebuild_fees.affected_cat == 'na','dk_public'] = 0.
        # ^  public dk losses, per cap
        
        rebuild_fees['dk_public_hh'] = rebuild_fees[['pcwgt','dk_public']].prod(axis=1,skipna=False)
        # ^ total dk suffered by each hh (and all the people it represents)
 
        rebuild_fees['dk_public_tot'] = rebuild_fees['dk_public_hh'].sum(level=event_level)
        # ^ dk_public_tot is the value of public asset losses, when a disaster (of type&magnitude) hits a single province

        rebuild_fees_tmp = pd.DataFrame(index=cats_event_ia.sum(level=['hazard','rp']).index)
        rebuild_fees_tmp['tot_k'] = cats_event_ia[['pcwgt','k']].prod(axis=1,skipna=False).sum(level=['hazard','rp'])
        # ^ tot_k is all the assets in the country

        rebuild_fees = pd.merge(rebuild_fees.reset_index(),rebuild_fees_tmp.reset_index(),on=['hazard','rp']).reset_index().set_index(event_level+['hhid','affected_cat'])

        cats_event_ia = cats_event_ia.reset_index().set_index(event_level+['hhid','affected_cat'])
        rebuild_fees = rebuild_fees.reset_index().set_index(event_level+['hhid','affected_cat'])

        rebuild_fees['frac_k'] = cats_event_ia[['pcwgt','k']].prod(axis=1,skipna=False)/rebuild_fees['tot_k']
        # ^ what fraction of all capital in the country is in each hh?
        
        rebuild_fees['pc_fee'] = rebuild_fees[['dk_public_tot','frac_k']].prod(axis=1)/rebuild_fees['pcwgt']
        # ^ this is the fraction of damages that each hh will pay
        # --> this is where it goes sideways, tho...
        # --> dk_public_tot is for a specific province/hazard/rp, and it needs to be distributed among everyone, nationally
        # --> but it only goes to the hh in the province
        
        rebuild_fees['hh_fee'] = rebuild_fees[['pc_fee','pcwgt']].prod(axis=1)

        cats_event_ia[['dk_public','pc_fee']] = rebuild_fees[['dk_public','pc_fee']]
        cats_event_ia = cats_event_ia.reset_index().set_index(event_level)

        #print(rebuild_fees[['dk_public_hh','hh_fee','frac_k']].sum(level=event_level).head(17))
        # ^ Check: we know this works if hh_fee = 'dk_public_hh'*'frac_k'

        ############################        
        # Make another output file... public_costs.csv
        # --> this contains the cost to each province/region of each disaster (hazardxrp) in another province
        public_costs = pd.DataFrame(index=macro_event.index)
        public_costs['tot_cost'] = rebuild_fees['dk_public_hh'].sum(level=event_level)
        public_costs['int_cost'] = (rebuild_fees[['dk_public_hh','frac_k']].sum(level=event_level)).prod(axis=1)
        public_costs['ext_cost'] = public_costs['tot_cost'] - public_costs['int_cost']
        public_costs['tmp'] = 1
        
        prov_k = pd.DataFrame(index=rebuild_fees.sum(level=event_level[0]).index)
        prov_k.index.names = ['contributer']

        prov_k['frac_k'] = rebuild_fees['frac_k'].sum(level=event_level[0])/rebuild_fees['frac_k'].sum()
        prov_k['tmp'] = 1
        prov_k = prov_k.reset_index()
        
        public_costs = pd.merge(public_costs.reset_index(),prov_k.reset_index(),on=['tmp']).reset_index().set_index(event_level).sort_index()
        public_costs = public_costs.drop(['index','level_0','tmp'],axis=1)
        # ^  broadcast prov index to public_costs (2nd provincial index)

        public_costs['transfer_k'] = public_costs[['tot_cost','frac_k']].prod(axis=1)
        public_costs['dw'] = None

        ############################
        # So we have cost of each disaster in each province to every other province
        # - need to calc welfare impact of these transfers
        public_costs = public_costs.reset_index()
        cats_event_ia = cats_event_ia.reset_index().set_index(['hhid'])
        
        for iP in public_costs.contributer.unique():
            
            tmp_df = cats_event_ia.loc[(cats_event_ia[event_level[0]]==iP),['k','c','c_5']].mean(level='hhid')
            tmp_df['pcwgt'] = cats_event_ia.loc[(cats_event_ia[event_level[0]]==iP),['pcwgt']].sum(level='hhid')

            tmp_df['pc_frac_k'] = tmp_df[['pcwgt','k']].prod(axis=1)/tmp_df[['pcwgt','k']].prod(axis=1).sum()
            # ^ this grabs a single instance of each hh in a given province
            # --> 'k' and 'c' are not distributed between {a,na} (use mean), but pcwgt is (use sum)
            # --> 'pc_frac_k' used to determine what they'll pay when a disaster happens elsewhere

            tmp_rho = macro_event['rho'].mean()
            tmp_ie     = macro_event['income_elast'].mean()
            tmp_t_reco = macro_event['T_rebuild_K'].mean()/3.
            tmp_mm     = macro_event['macro_multiplier'].mean()
            c_mean     = float(cats_event_ia[['pcwgt','c']].prod(axis=1).sum()/cats_event_ia['pcwgt'].sum())
            h = 1.E-4

            wprime_rev  = ((c_mean+h)**(1-tmp_ie)-(c_mean-h)**(1-tmp_ie))/(2*h)
            wprime_rev2 = wprime_rev/tmp_rho
            # ^ these *could* vary by province/event, but don't (for now), so I'll use them outside the pandas dfs.
            
            for iRecip in public_costs[event_level[0]].unique():
                for iHaz in public_costs.hazard.unique():
                    for iRP in public_costs.rp.unique():

                        # Calculate wprime
                        tmp_wp = None
                        if is_local_welfare:
                            tmp_gdp = macro_event.loc[(macro_event[economy]==iP),'gdp_pc_pp_prov'].mean()
                            tmp_wp =(welf(tmp_gdp/tmp_rho+h,tmp_ie)-welf(tmp_gdp/tmp_rho-h,tmp_ie))/(2*h)
                        else: tmp_wp =(welf(macro_event['gdp_pc_pp_nat'].mean()/tmp_rho+h,tmp_ie)-welf(macro_event['gdp_pc_pp_nat'].mean()/tmp_rho-h,tmp_ie))/(2*h)

                        tmp_cost = float(public_costs.loc[((public_costs[event_level[0]]==iRecip)&(public_costs.contributer == iP)
                                                     &(public_costs.hazard == iHaz)&(public_costs.rp==iRP)),'transfer_k'])
                        # ^ this identifies the amount that a province (iP, above) will contribute to another province when a disaster occurs

                        tmp_df['tmp_dk'] = tmp_cost*tmp_df['pc_frac_k']
                        tmp_df['tmp_dk_pc'] = (tmp_df['tmp_dk']/tmp_df['pcwgt'])
                        tmp_df['tmp_dc_npv'] = tmp_mm*(tmp_df['tmp_dk']/tmp_df['pcwgt'])

                        tmp_df['dw'] = 0.
                        if not is_revised_dw:
                            tmp_df['dw'] = tmp_df['pcwgt']*(welf1(tmp_df['c']/tmp_rho, tmp_ie, tmp_df['c_5']/tmp_rho)
                                                            - welf1(tmp_df['c']/tmp_rho-tmp_df['tmp_dc_npv'], tmp_ie,tmp_df['c_5']/tmp_rho))/tmp_wp
                        else:
                            # Set-up to be able to calculate integral
                            tmp_df['const'] = ((tmp_df['c']**(1.-tmp_ie))/(1.-tmp_ie))
                            tmp_df['integ'] = 0.

                            x_min, x_max, n_steps = 0.,10.,20.
                            int_dt,step_dt = np.linspace(x_min,x_max,num=n_steps,endpoint=True,retstep=True)
                            # ^ make sure that, if T_recon changes, so does x_max!

                            # Calculate integral
                            for i_dt in int_dt:
                                tmp_df['integ'] += step_dt*(((1.-(tmp_df['tmp_dk_pc']/tmp_df['c'])*math.e**(-i_dt/tmp_t_reco))**(1-tmp_ie)-1)*math.e**(-tmp_rho*i_dt))
                                # ^ in main function, we have 'dc_post_pds' instead of 'tmp_dk', but here assuming no offsetting of fee people are paying
                                
                            # put it all together, including w_prime:
                            tmp_df['dw'] = tmp_df[['pcwgt','const','integ']].prod(axis=1)/wprime_rev
                            tmp_df['dw2'] = tmp_df[['pcwgt','const','integ']].prod(axis=1)/wprime_rev2
                            
                        public_costs.loc[((public_costs[event_level[0]]==iRecip)&(public_costs.contributer==iP)&(public_costs.hazard==iHaz)&(public_costs.rp==iRP)),'dw'] = tmp_df['dw'].sum()
                        
        cats_event_ia = cats_event_ia.reset_index().set_index(event_level)
        public_costs = public_costs.reset_index().set_index(event_level).drop('index',axis=1)

        ############################
        # Affected hh:
        cats_event_ia['dc'] = ((1-macro_event['tau_tax'])*(cats_event_ia['dk']-cats_event_ia['dk_public']) 
                               + cats_event_ia['gamma_SP']*macro_event[['tau_tax','dk_event']].prod(axis=1)
                               + cats_event_ia['pc_fee'])

        # Not affected hh:
        cats_event_ia.loc[(cats_event_ia.affected_cat=='na'),'dc'] = (cats_event_ia.loc[(cats_event_ia.affected_cat=='na'),'gamma_SP']*macro_event[['tau_tax','dk_event']].prod(axis=1)
                                                                      + cats_event_ia.loc[(cats_event_ia.affected_cat=='na'),'pc_fee'])
        
        cats_event_ia['dc_0'] = (1-macro_event['tau_tax'])*cats_event_ia['dk'] + cats_event_ia['gamma_SP']*macro_event[['tau_tax','dk_event']].prod(axis=1)

        cats_event_ia.head(50).to_csv('~/Desktop/my_ceia.csv')

    # This term is the impact on income from labor
    # cats_event_ia['dc_1'] = (1-macro_event['tau_tax'])*cats_event_ia['dk']

    # This term is the impact on national transfers
    # cats_event_ia['dc_2'] = cats_event_ia['gamma_SP']*macro_event['tau_tax'] *macro_event['dk_event'] 

    # NPV consumption losses accounting for reconstruction and productivity of capital (pre-response)
    cats_event_ia['dc_npv_pre'] = cats_event_ia['dc']*macro_event['macro_multiplier']

    return macro_event, cats_event_ia, public_costs


def calculate_response(myCountry,pol_str,macro_event,cats_event_ia,event_level,helped_cats,default_rp,option_CB,optionFee='tax',optionT='data', optionPDS='unif_poor', optionB='data',loss_measure='dk',fraction_inside=1, share_insured=.25):

    cats_event_iah = concat_categories(cats_event_ia,cats_event_ia, index= helped_cats).reset_index(helped_cats.name).sort_index().dropna()

    # Baseline case (no insurance):
    cats_event_iah['help_received'] = 0
    cats_event_iah['help_fee'] =0

    macro_event, cats_event_iah = compute_response(myCountry, pol_str,macro_event, cats_event_iah, event_level,default_rp,option_CB,optionT=optionT, 
                                                   optionPDS=optionPDS, optionB=optionB, optionFee=optionFee, fraction_inside=fraction_inside, loss_measure = loss_measure)
    
    cats_event_iah.drop('protection',axis=1, inplace=True)	      

    return macro_event, cats_event_iah
	
def compute_response(myCountry, pol_str, macro_event, cats_event_iah, event_level, default_rp, option_CB,optionT='data', optionPDS='unif_poor', optionB='data', optionFee='tax', fraction_inside=1, loss_measure='dk'):    

    print('NB: when summing over cats_event_iah, be aware that each hh appears 4X in the file: {a,na}x{helped,not_helped}')
    
    """Computes aid received,  aid fee, and other stuff, from losses and PDS options on targeting, financing, and dimensioning of the help.
    Returns copies of macro_event and cats_event_iah updated with stuff"""

    macro_event    = macro_event.copy()
    cats_event_iah = cats_event_iah.copy()

    macro_event['fa'] = (cats_event_iah.loc[(cats_event_iah.affected_cat=='a'),'pcwgt'].sum(level=event_level)/(cats_event_iah['pcwgt'].sum(level=event_level))).fillna(1E-8)

    # Edit: no factor of 2 in denominator because we're only summing affected households here
    #macro_event['fa'] = agg_to_event_level(cats_event_iah,'fa',event_level)/2 # because cats_event_ia is duplicated in cats_event_iah, cats_event_iah.n.sum(level=event_level) is 2 instead of 1, here /2 is to correct it.

    ####targeting errors
    if optionPDS == 'fiji_SPS' or optionPDS == 'fiji_SPP':
        macro_event['error_incl'] = 1.0
        macro_event['error_excl'] = 0.0
    elif optionT=='perfect':
        macro_event['error_incl'] = 0
        macro_event['error_excl'] = 0    
    elif optionT=='prop_nonpoor_lms':
        macro_event['error_incl'] = 0
        macro_event['error_excl'] = 1-25/80  #25% of pop chosen among top 80 DO receive the aid
    elif optionT=='data':
        macro_event['error_incl']=(1)/2*macro_event['fa']/(1-macro_event['fa'])
        macro_event['error_excl']=(1)/2
    elif optionT=='x33':
        macro_event['error_incl']= .33*macro_event['fa']/(1-macro_event['fa'])
        macro_event['error_excl']= .33
    elif optionT=='incl':
        macro_event['error_incl']= .33*macro_event['fa']/(1-macro_event['fa'])
        macro_event['error_excl']= 0
    elif optionT=='excl':
        macro_event['error_incl']= 0
        macro_event['error_excl']= 0.33

    else:
        print('unrecognized targeting error option '+optionT)
        return None
            
    #counting (mind self multiplication of n)
    df_index = cats_event_iah.index.names    
    cats_event_iah = pd.merge(cats_event_iah.reset_index(),macro_event.reset_index()[[i for i in macro_event.index.names]+['error_excl','error_incl']],on=[i for i in macro_event.index.names])
                              
    for aWGT in ['hhwgt','pcwgt','pcwgt_ae']:
        cats_event_iah.loc[(cats_event_iah.helped_cat=='helped')    & (cats_event_iah.affected_cat=='a') ,aWGT]*=(1-cats_event_iah['error_excl'])
        cats_event_iah.loc[(cats_event_iah.helped_cat=='not_helped')& (cats_event_iah.affected_cat=='a') ,aWGT]*=(  cats_event_iah['error_excl'])
        cats_event_iah.loc[(cats_event_iah.helped_cat=='helped')    & (cats_event_iah.affected_cat=='na'),aWGT]*=(  cats_event_iah['error_incl'])  
        cats_event_iah.loc[(cats_event_iah.helped_cat=='not_helped')& (cats_event_iah.affected_cat=='na'),aWGT]*=(1-cats_event_iah['error_incl'])

    cats_event_iah = cats_event_iah.reset_index().set_index(df_index).drop([icol for icol in ['index','error_excl','error_incl'] if icol in cats_event_iah.columns],axis=1)
    cats_event_iah = cats_event_iah.drop(['index'],axis=1)
    
    # MAXIMUM NATIONAL SPENDING ON SCALE UP
    macro_event['max_increased_spending'] = 0.05

    # max_aid is per cap, and it is constant for all disasters & provinces
    # --> If this much were distributed to everyone in the country, it would be 5% of GDP
    # --> All of these '.mean()' are because I'm bad at Pandas. The arrays are all the same value, and we want to pull out a single instance here
    macro_event['max_aid'] = macro_event['max_increased_spending'].mean()*macro_event[['gdp_pc_pp_prov','pop']].prod(axis=1).sum(level=['hazard','rp']).mean()/macro_event['pop'].sum(level=['hazard','rp']).mean()

    if optionFee == 'insurance_premium':
        temp = cats_event_iah.copy()
	
    if optionPDS=='no':
        macro_event['aid'] = 0
        macro_event['need'] = 0
        cats_event_iah['help_received']=0
        optionB='no'

    if optionPDS == 'fiji_SPP':
        
        sp_payout = pd.DataFrame(index=macro_event.sum(level='rp').index)
        sp_payout = sp_payout.reset_index()

        sp_payout['monthly_allow'] = 177#FJD
        
        sp_payout['frac_core'] = 0.0
        #sp_payout.loc[sp_payout.rp >= 20,'frac_core'] = 1.0
        sp_payout.loc[sp_payout.rp >= 10,'frac_core'] = 1.0        

        sp_payout['frac_add'] = 0.0
        #sp_payout.loc[(sp_payout.rp >=  5)&(sp_payout.rp < 10),'frac_add'] = 0.25
        sp_payout.loc[(sp_payout.rp >= 10)&(sp_payout.rp < 20),'frac_add'] = 0.50
        sp_payout.loc[(sp_payout.rp >= 20)&(sp_payout.rp < 40),'frac_add'] = 0.75
        sp_payout.loc[(sp_payout.rp >= 40),'frac_add'] = 1.00

        sp_payout['multiplier'] = 1.0
        sp_payout.loc[(sp_payout.rp >=  40)&(sp_payout.rp <  50),'multiplier'] = 2.0
        sp_payout.loc[(sp_payout.rp >=  50)&(sp_payout.rp < 100),'multiplier'] = 3.0
        sp_payout.loc[(sp_payout.rp >= 100),'multiplier'] = 4.0

        #sp_payout['payout_core'] = sp_payout[['monthly_allow','frac_core','multiplier']].prod(axis=1)
        #sp_payout['payout_add']  = sp_payout[['monthly_allow', 'frac_add','multiplier']].prod(axis=1)
        # ^ comment out these lines when uncommenting below
        sp_payout['payout'] = sp_payout[['monthly_allow','multiplier']].prod(axis=1)
        # ^ this line is for when we randomly choose people in each group

        sp_payout.to_csv('../output_country/FJ/SPP_details.csv')
 
        cats_event_iah = pd.merge(cats_event_iah.reset_index(),sp_payout[['rp','payout','frac_core','frac_add']].reset_index(),on=['rp'])
        cats_event_iah = cats_event_iah.reset_index().set_index(['Division','hazard','hhid','rp','affected_cat','helped_cat'])
        cats_event_iah = cats_event_iah.drop([i for i in ['level_0'] if i in cats_event_iah.columns],axis=1)

        # Generate random numbers to determine payouts
        cats_event_iah['SP_lottery'] = np.random.uniform(0.0,1.0,cats_event_iah.shape[0])

        # Calculate payouts for core: 100% payout for RP >= 20
        cats_event_iah.loc[(cats_event_iah.SPP_core == True)&(cats_event_iah.SP_lottery<cats_event_iah.frac_core),'help_received'] = cats_event_iah.loc[(cats_event_iah.SPP_core == True)&(cats_event_iah.SP_lottery<cats_event_iah.frac_core),'payout']/cats_event_iah.loc[(cats_event_iah.SPP_core == True)&(cats_event_iah.SP_lottery<cats_event_iah.frac_core),'hhsize']
        
        # Calculate payouts for additional: variable payout based on lottery
        cats_event_iah.loc[(cats_event_iah.SPP_add==True)&(cats_event_iah.SP_lottery<cats_event_iah.frac_add),'SP_lottery_win'] = True
        cats_event_iah['SP_lottery_win'] = cats_event_iah['SP_lottery_win'].fillna(False)

        #cats_event_iah.loc[(cats_event_iah.rp>= 5)&(cats_event_iah.rp<10)&(cats_event_iah.SPP_add==True)&(cats_event_iah.SP_lottery <= 0.25),'SP_lottery_win'] = True
        #cats_event_iah.loc[(cats_event_iah.rp>=10)&(cats_event_iah.rp<20)&(cats_event_iah.SPP_add==True)&(cats_event_iah.SP_lottery <= 0.50),'SP_lottery_win'] = True
        #cats_event_iah.loc[(cats_event_iah.rp>=20)&(cats_event_iah.rp<40)&(cats_event_iah.SPP_add==True)&(cats_event_iah.SP_lottery <= 0.75),'SP_lottery_win'] = True
        #cats_event_iah.loc[(cats_event_iah.rp>=40)&(cats_event_iah.SPP_add==True),'SP_lottery_win'] = True
        # ^ this info already encoded in frac_add
        
        cats_event_iah.loc[(cats_event_iah.SP_lottery_win==True),'help_received'] = cats_event_iah.loc[(cats_event_iah.SP_lottery_win==True),'payout']/cats_event_iah.loc[(cats_event_iah.SP_lottery<cats_event_iah.frac_core),'hhsize']

        cats_event_iah = cats_event_iah.reset_index().set_index(['Division','hazard','rp','hhid']).sortlevel()
        # ^ Take helped_cat and affected_cat out of index. Need to slice on helped_cat, and the rest of the code doesn't want hhtypes in index
  
        cats_event_iah.loc[(cats_event_iah.helped_cat=='not_helped'),'help_received'] = 0
        cats_event_iah = cats_event_iah.drop([i for i in ['level_0','SPP_core','SPP_add','payout','frac_core','frac_add','SP_lottery','SP_lottery_win'] if i in cats_event_iah.columns],axis=1)

        my_out = cats_event_iah[['help_received','pcwgt']].prod(axis=1).sum(level=['hazard','rp'])
        my_out.to_csv('../output_country/FJ/SPplus_expenditure.csv')
        my_out,_ = average_over_rp(my_out.sum(level=['rp']),default_rp)
        my_out.sum().to_csv('../output_country/FJ/SPplus_expenditure_annual.csv')

    if optionPDS=='fiji_SPS':

        sp_payout = macro_event['dk_event'].copy()
        sp_payout = sp_payout.sum(level=['hazard','rp'])
        sp_payout = sp_payout.reset_index().set_index(['hazard'])

        sp_200yr = sp_payout.loc[sp_payout.rp==200,'dk_event']
        
        sp_payout = pd.concat([sp_payout,sp_200yr],axis=1,join='inner')
        sp_payout.columns = ['rp','dk_event','benchmark_losses']

        sp_payout['f_benchmark'] = (sp_payout['dk_event']/sp_payout['benchmark_losses']).clip(lower=0.0,upper=1.0)
        sp_payout.loc[(sp_payout.rp < 10),'f_benchmark'] = 0.0
        sp_payout = sp_payout.drop(['dk_event','benchmark_losses'],axis=1)
        sp_payout = sp_payout.reset_index().set_index(['hazard','rp'])
        sp_payout.to_csv('../output_country/FJ/SPS_details.csv')

        cats_event_iah = pd.merge(cats_event_iah.reset_index(),sp_payout.reset_index(),on=['hazard','rp'])
        cats_event_iah = cats_event_iah.reset_index().set_index(['Division','hazard','rp','hhid']).sortlevel()

        # paying out per cap
        cats_event_iah['help_received'] = 0

        print('\nTotal N Households:',cats_event_iah['hhwgt'].sum(level=['hazard','rp']).mean())
        print('\nSPS enrollment:',cats_event_iah.loc[(cats_event_iah.SP_SPS==True),['nOlds','hhwgt']].prod(axis=1).sum(level=['hazard','rp']).mean())
        print('\nCPP enrollment:',cats_event_iah.loc[(cats_event_iah.SP_CPP==True),'hhwgt'].sum(level=['hazard','rp']).mean())
        print('\nFAP enrollment:',cats_event_iah.loc[(cats_event_iah.SP_FAP==True),'hhwgt'].sum(level=['hazard','rp']).mean())
        print('\nPBS enrollment:',cats_event_iah.loc[(cats_event_iah.SP_PBS==True),'hhwgt'].sum(level=['hazard','rp']).mean())

        print('\nMax SPS expenditure =',(cats_event_iah.loc[(cats_event_iah.SP_SPS==True),['hhwgt','nOlds']].prod(axis=1).sum()*300+
                                         cats_event_iah.loc[(cats_event_iah.SP_CPP==True),'hhwgt'].sum()*300+
                                         cats_event_iah.loc[(cats_event_iah.SP_PBS==True),'hhwgt'].sum()*600)/(17*4),'\n')
        
        cats_event_iah.loc[(cats_event_iah.SP_SPS==True),'help_received']+=300*(cats_event_iah.loc[(cats_event_iah.SP_SPS==True),['hhwgt','nOlds','f_benchmark']].prod(axis=1)/
                                                                                cats_event_iah.loc[(cats_event_iah.SP_SPS==True),'pcwgt']).fillna(0)
        cats_event_iah.loc[(cats_event_iah.SP_CPP==True),'help_received']+=300*(cats_event_iah.loc[(cats_event_iah.SP_CPP==True),['hhwgt','f_benchmark']].prod(axis=1)/
                                                                                cats_event_iah.loc[(cats_event_iah.SP_CPP==True),'pcwgt']).fillna(0)
        cats_event_iah.loc[(cats_event_iah.SP_PBS==True),'help_received']+=600*(cats_event_iah.loc[(cats_event_iah.SP_PBS==True),['hhwgt','f_benchmark']].prod(axis=1)/
                                                                                cats_event_iah.loc[(cats_event_iah.SP_PBS==True),'pcwgt']).fillna(0)
        cats_event_iah.loc[(cats_event_iah.helped_cat=='not_helped'),'help_received'] = 0
        my_out = cats_event_iah[['help_received','pcwgt']].prod(axis=1).sum(level=['hazard','rp'])
        my_out.to_csv('../output_country/FJ/SPS_expenditure.csv')
        my_out,_ = average_over_rp(my_out.sum(level=['rp']),default_rp)
        my_out.sum().to_csv('../output_country/FJ/SPS_expenditure_annual.csv')

        cats_event_iah = cats_event_iah.drop(['f_benchmark'],axis=1)

    elif optionPDS=='unif_poor':

        cats_event_iah['help_received'] = 0        

        # For this policy:
        # --> help_received = 0.8*average losses of lowest quintile (households)
        cats_event_iah.loc[(cats_event_iah.helped_cat=='helped')&(cats_event_iah.affected_cat=='a'),'help_received'] = macro_event['shareable']*cats_event_iah.loc[(cats_event_iah.affected_cat=='a')&(cats_event_iah.quintile==1),[loss_measure,'pcwgt']].prod(axis=1).sum(level=event_level)/cats_event_iah.loc[(cats_event_iah.affected_cat=='a')&(cats_event_iah.quintile==1),'pcwgt'].sum(level=event_level)

        # These should be zero here, but just to make sure...
        cats_event_iah.ix[(cats_event_iah.helped_cat=='not_helped'),'help_received']=0
        cats_event_iah.ix[(cats_event_iah.affected_cat=='na'),'help_received']=0
        # Could test with these:
        #assert(cats_event_iah.ix[(cats_event_iah.helped_cat=='not_helped'),'help_received'].sum()==0)
        #assert(cats_event_iah.ix[(cats_event_iah.affected_cat=='na'),'help_received'].sum()==0)


    elif optionPDS=='unif_poor_only':
        cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')&(cats_event_iah.affected_cat=='a')&(cats_event_iah.quintile==1),'help_received']=macro_event['shareable']*cats_event_iah.loc[(cats_event_iah.affected_cat=='a')&(cats_event_iah.quintile==1),[loss_measure,'pcwgt']].prod(axis=1).sum(level=event_level)/cats_event_iah.loc[(cats_event_iah.affected_cat=='a')&(cats_event_iah.quintile==1),'pcwgt'].sum(level=event_level)

        # These should be zero here, but just to make sure...
        cats_event_iah.ix[(cats_event_iah.helped_cat=='not_helped')|(cats_event_iah.quintile > 1),'help_received']=0
        cats_event_iah.ix[(cats_event_iah.affected_cat=='na')|(cats_event_iah.quintile > 1),'help_received']=0

        print('Calculating loss measure\n')

    elif optionPDS=='prop':
        if not 'has_received_help_from_PDS_cat' in cats_event_iah.columns:
            cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='a'),'help_received']= macro_event['shareable']*cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='a'),loss_measure]
            cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='na'),'help_received']= macro_event['shareable']*cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='a'),loss_measure]
            cats_event_iah.ix[cats_event_iah.helped_cat=='not_helped','help_received']=0		

        else:
            cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='a')  & (cats_event_iah.has_received_help_from_PDS_cat=='helped'),'help_received']= macro_event['shareable']*cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='a')  & (cats_event_iah.has_received_help_from_PDS_cat=='helped'),loss_measure]
            cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='na')  & (cats_event_iah.has_received_help_from_PDS_cat=='helped'),'help_received']= macro_event['shareable']*cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='a')  & (cats_event_iah.has_received_help_from_PDS_cat=='helped'),loss_measure]			
            cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='a')  & (cats_event_iah.has_received_help_from_PDS_cat=='not_helped'),'help_received']= macro_event['shareable']*cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='a')  & (cats_event_iah.has_received_help_from_PDS_cat=='helped'),loss_measure]
            cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='na')  & (cats_event_iah.has_received_help_from_PDS_cat=='not_helped'),'help_received']= macro_event['shareable']*cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')& (cats_event_iah.affected_cat=='a')  & (cats_event_iah.has_received_help_from_PDS_cat=='helped'),loss_measure]			
            cats_event_iah.ix[cats_event_iah.helped_cat=='not_helped','help_received']=0           
		
    # What is the function of need?
    # --> Defining it as the cost of disaster assistance distributed among all people in each province
    # --> 'need' is household, not per person!!
    if optionPDS != 'fiji_SPS':
        macro_event['need'] = cats_event_iah[['help_received','pcwgt']].prod(axis=1).sum(level=event_level)/(cats_event_iah['pcwgt'].sum(level=event_level))
        macro_event['need_tot'] = cats_event_iah[['help_received','pcwgt']].prod(axis=1).sum(level=event_level)

    #actual aid reduced by capacity
    if optionPDS == 'no':
        macro_event['my_help_fee'] = 0

    elif optionPDS == 'fiji_SPS' or optionPDS == 'fiji_SPP':
        #macro_event['my_help_fee'] = macro_event['need']
        pass

    elif optionB=='data' or optionB=='unif_poor':

        # See discussion above. This is the cost 
        print('No upper limit on help_received coded at this point...if we did exceed 5% of GDP, the help_fee would just be capped')
        macro_event['my_help_fee'] = macro_event['need'].clip(upper=macro_event['max_aid'])
    else:
        assert(False)
        
    #elif optionB=='max01':
    #    macro_event['max_aid'] = 0.01*macro_event['gdp_pc_pp_nat']
    #    macro_event['aid'] = (macro_event['need']).clip(upper=macro_event['max_aid']) 
    #elif optionB=='max05':
    #    macro_event['max_aid'] = 0.05*macro_event['gdp_pc_pp_nat']
    #    macro_event['aid'] = (macro_event['need']).clip(upper=macro_event['max_aid'])
    #elif optionB=='unlimited':
    #    macro_event['aid'] = macro_event['need']
    #elif optionB=='one_per_affected':
    #    d = cats_event_iah.ix[(cats_event_iah.affected_cat=='a')]        
    #    d['un']=1
    #    macro_event['need'] = agg_to_event_level(d,'un',event_level)
    #    macro_event['aid'] = macro_event['need']
    #elif optionB=='one_per_helped':
    #    d = cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')]        
    #    d['un']=1
    #    macro_event['need'] = agg_to_event_level(d,'un',event_level)
    #    macro_event['aid'] = macro_event['need']
    #elif optionB=='one':
    #    macro_event['aid'] = 1
    #elif optionB=='no':
    #    pass	
    
    #NO!!!!!
    #if optionPDS=='unif_poor':
        # NO. we have already calculated help_received.
        #macro_event['unif_aid'] = macro_event['aid']

    #elif optionPDS=='unif_poor_only':
    #    macro_event['unif_aid'] = macro_event['aid']/(cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')&(cats_event_iah.quintile==1),'pcwgt'].sum(level=event_level)) 
    #    cats_event_iah.ix[(cats_event_iah.helped_cat=='helped')&(cats_event_iah.quintile==1),'help_received'] = macro_event['unif_aid']
    #    cats_event_iah.ix[(cats_event_iah.helped_cat=='not_helped')|(cats_event_iah.quintile==1),'help_received']=0
    
    #if optionPDS=='prop':
    #    cats_event_iah['help_received'] = macro_event['aid']/macro_event['need']*cats_event_iah['help_received'] 		
		
    if optionFee=='tax':

        # Original code:
        #cats_event_iah['help_fee'] = fraction_inside*macro_event['aid']*cats_event_iah['k']/agg_to_event_level(cats_event_iah,'k',event_level)
        # ^ this only manages transfers within each province 
        # -- we still need to multiply 'my_help_fee' by weight, 
        # -- If 1 hh had all the capital, its help_fee would be my_help_fee, which is the per capita value

        cats_event_iah['help_fee'] = 0
        if optionPDS == 'fiji_SPS' or optionPDS == 'fiji_SPP':
            
            cats_event_iah = pd.merge(cats_event_iah.reset_index(),(cats_event_iah[['help_received','pcwgt']].prod(axis=1).sum(level=['hazard','rp'])).reset_index(),on=['hazard','rp'])
            cats_event_iah = cats_event_iah.reset_index().set_index(event_level)
            cats_event_iah = cats_event_iah.rename(columns={0:'totex'}).drop(['index','level_0'],axis=1)
            ## ^ total expenditure

            cats_event_iah = pd.merge(cats_event_iah.reset_index(),(cats_event_iah[['k','pcwgt']].prod(axis=1).sum(level=['hazard','rp'])).reset_index(),on=['hazard','rp'])
            cats_event_iah = cats_event_iah.reset_index().set_index(event_level)
            cats_event_iah = cats_event_iah.rename(columns={0:'totk'})          
            
            cats_event_iah['help_fee'] = (cats_event_iah[['totex','k','pcwgt']].prod(axis=1)/cats_event_iah['totk'])/cats_event_iah['pcwgt']
            # ^ could eliminate the two instances of 'pcwgt', but I'm leaving them in to make clear to future me how this was constructed

            cats_event_iah = cats_event_iah.reset_index().set_index(event_level)
            cats_event_iah = cats_event_iah.drop(['index','totex','totk','nOlds','SP_CPP','SP_FAP','SP_FNPF','SP_SPS','SP_PBS'],axis=1)

            # Something like this should evaluate to true
            #assert((cats_event_iah[['pcwgt','help_received']].prod(axis=1).sum(level=['hazard','rp'])).ix['TC'] == 
            #       (cats_event_iah[['pcwgt','help_fee']].prod(axis=1).sum(level=['hazard','rp'])).ix['TC'])

        else:
            cats_event_iah.loc[cats_event_iah.pcwgt != 0,'help_fee'] = (cats_event_iah.loc[cats_event_iah.pcwgt != 0,['help_received','pcwgt']].prod(axis=1).sum(level=event_level) * 
                                                                        # ^ total expenditure
                                                                        (cats_event_iah.loc[cats_event_iah.pcwgt != 0,['k','pcwgt']].prod(axis=1) /
                                                                         cats_event_iah.loc[cats_event_iah.pcwgt != 0,['k','pcwgt']].prod(axis=1).sum(level=event_level)) /
                                                                        # ^ weighted average of capital
                                                                        cats_event_iah.loc[cats_event_iah.pcwgt != 0,'pcwgt']) 
                                                                        # ^ help_fee is per individual!

    elif optionFee=='insurance_premium':
        print(optionFee)
        cats_event_iah = cats_event_iah.reset_index().set_index([economy,'hazard','helped_cat',  'affected_cat',     'hhid','rp']) 

#        cats_event_iah = cats_event_iah.reset_index().set_index(['province','hazard','helped_cat',  'affected_cat',     'hhid','has_received_help_from_PDS_cat','rp'])
        averaged,proba_serie = average_over_rp(cats_event_iah['help_received'],default_rp,cats_event_iah['protection'].squeeze())
#        proba_serie = proba_serie.reset_index().set_index(['province','hazard','helped_cat',  'affected_cat',     'hhid','has_received_help_from_PDS_cat','rp']) 
        proba_serie = proba_serie.reset_index().set_index([economy,'hazard','helped_cat',  'affected_cat',     'hhid','rp']) 
        cats_event_iah['help_received'] = broadcast_simple(averaged,cats_event_iah.index)
#        cats_event_iah.help_received = cats_event_iah.help_received/proba_serie.prob
        cats_event_iah = cats_event_iah.reset_index().set_index(event_level)
#        aa = cats_event_iah.loc[('Ampara',slice(None),[5,10]),['help_received','help_fee','helped_cat','affected_cat']]
#        aa1 = aa[aa.helped_cat=='helped']
#        aa2 = aa[aa.helped_cat=='not_helped']
        cats_event_iah.ix[cats_event_iah.helped_cat=='helped','help_received_ins'] = cats_event_iah.ix[cats_event_iah.helped_cat=='helped','help_received']
        cats_event_iah.ix[cats_event_iah.helped_cat=='not_helped','help_received_ins'] = cats_event_iah.ix[cats_event_iah.helped_cat=='helped','help_received']
        
        ###
        cats_event_iah['help_fee'] = agg_to_event_level(cats_event_iah,'help_received',event_level)/(cats_event_iah.n.sum(level=event_level))*cats_event_iah['help_received_ins']/agg_to_event_level(cats_event_iah,'help_received_ins',event_level)
        print('Calculation of help_fee is definitely wrong!')
        assert(False)
        ###

        cats_event_iah.ix[cats_event_iah.affected_cat=='na','help_received'] = 0
        cats_event_iah.ix[cats_event_iah.helped_cat=='not_helped','help_received'] = 0
#        cats_event_iah.drop('help_received_ins',axis=1,inplace=True)
#       print(cats_event_iah[['help_fee','help_received']])
#       print(temp[['help_fee','help_received']])
#        cats_event_iah[['help_received','help_fee']]+=temp[['help_received','help_fee']]
    return macro_event, cats_event_iah


def compute_dW(myCountry,pol_str,macro_event,cats_event_iah,event_level,option_CB,return_stats=True,return_iah=True,is_revised_dw=True):
    cats_event_iah = cats_event_iah.reset_index().set_index(event_level+['hhid','affected_cat','helped_cat'])

    cats_event_iah['dc_npv_post'] = cats_event_iah['dc_npv_pre']-cats_event_iah['help_received']+cats_event_iah['help_fee']*option_CB
    if is_revised_dw:
        print('changing dc to include help_received and help_fee, since instantaneous loss is used instead of npv for dw')
        print('how does timing affect the appropriateness of this?')
        cats_event_iah['dc_post_pds'] = cats_event_iah['dc']-cats_event_iah['help_received']+cats_event_iah['help_fee']*option_CB        
    
    cats_event_iah['dw'] = calc_delta_welfare(cats_event_iah,macro_event,is_revised_dw)
    cats_event_iah = cats_event_iah.reset_index().set_index(event_level)


    ###########
    #OUTPUT
    df_out = pd.DataFrame(index=macro_event.index)
    
    #aggregates dK and delta_W at df level
    # --> dK, dW are averages per individual
    df_out['dK']        = cats_event_iah[['dk'       ,'pcwgt']].prod(axis=1).sum(level=event_level)/cats_event_iah['pcwgt'].sum(level=event_level)
    #df_out['dK_public'] = cats_event_iah[['dk_public','pcwgt']].prod(axis=1).sum(level=event_level)/cats_event_iah['pcwgt'].sum(level=event_level)
    df_out['delta_W']   = cats_event_iah[['dw'       ,'pcwgt']].prod(axis=1).sum(level=event_level)/cats_event_iah['pcwgt'].sum(level=event_level)

    # dktot is already summed with RP -- just add them normally to get losses
    df_out['dKtot']       =      df_out['dK']*cats_event_iah['pcwgt'].sum(level=event_level)#macro_event['pop']
    df_out['delta_W_tot'] = df_out['delta_W']*cats_event_iah['pcwgt'].sum(level=event_level)#macro_event['pop'] 
    # ^ dK and dK_tot include both public and private losses

    df_out['average_aid_cost_pc'] = (cats_event_iah[['pcwgt','help_fee']].prod(axis=1).sum(level=event_level))/cats_event_iah['pcwgt'].sum(level=event_level)
    
    if return_stats:
        if not 'has_received_help_from_PDS_cat' in cats_event_iah.columns:
            stats = np.setdiff1d(cats_event_iah.columns,event_level+['helped_cat','affected_cat','hhid']+[i for i in ['province'] if i in cats_event_iah.columns])
        else:
            stats = np.setdiff1d(cats_event_iah.columns,event_level+['helped_cat','affected_cat','hhid','has_received_help_from_PDS_cat']+[i for i in ['province'] if i in cats_event_iah.columns])
		
        print('stats are '+','.join(stats))
        df_stats = agg_to_event_level(cats_event_iah,stats,event_level)
        df_out[df_stats.columns]=df_stats 
		    
    if return_iah:
        return df_out,cats_event_iah
    else: 
        return df_out

	
def process_output(pol_str,out,macro_event,economy,default_rp,return_iah=True,is_local_welfare=False,is_revised_dw=True):

    #unpacks if needed
    if return_iah:
        dkdw_event,cats_event_iah  = out

    else:
        dkdw_event = out

    ##AGGREGATES LOSSES
    #Averages over return periods to get dk_{hazard} and dW_{hazard}
    dkdw_h = average_over_rp1(dkdw_event,default_rp,macro_event['protection']).set_index(macro_event.index)
    macro_event[dkdw_h.columns]=dkdw_h

    #computes socio economic capacity and risk at economy level
    macro = calc_risk_and_resilience_from_k_w(macro_event,cats_event_iah,economy,is_local_welfare,is_revised_dw)

    ###OUTPUTS
    if return_iah:
        return macro, cats_event_iah
    else:
        return macro
	
def unpack_social(m,cat):
    """Compute social from gamma_SP, taux tax and k and avg_prod_k"""
    c  = cat.c
    gs = cat.gamma_SP

    social = gs*m.gdp_pc_pp_nat*m.tau_tax/(c+1.0e-10) #gdp*tax should give the total social protection. gs=each one's social protection/(total social protection). social is defined as t(which is social protection)/c_i(consumption)

    return social
    
def same_rps_all_hazards(fa_ratios):
    ''' inspired by interpolate_rps but made to make sure all hazards have the same return periods (not that the protection rps are included by hazard)'''
    flag_stack= False
    if 'rp' in get_list_of_index_names(fa_ratios):
        fa_ratios = fa_ratios.unstack('rp')
        flag_stack = True
        
    #in case of a Multicolumn dataframe, perform this function on each one of the higher level columns
    if type(fa_ratios.columns)==pd.MultiIndex:
        keys = fa_ratios.columns.get_level_values(0).unique()
        return pd.concat({col:same_rps_all_hazards(fa_ratios[col]) for col in  keys}, axis=1).stack('rp')

    ### ACTUAL FUNCTION    
    #figures out all the return periods to be included
    all_rps = fa_ratios.columns.tolist()
    
    fa_ratios_rps = fa_ratios.copy()
    
    fa_ratios_rps = fa_ratios_rps.reindex_axis(sorted(fa_ratios_rps.columns), axis=1)
    # fa_ratios_rps = fa_ratios_rps.interpolate(axis=1,limit_direction="both",downcast="infer")
    fa_ratios_rps = fa_ratios_rps.interpolate(axis=1,limit_direction="both")
    if flag_stack:
        fa_ratios_rps = fa_ratios_rps.stack('rp')
    
    return fa_ratios_rps    


	
def interpolate_rps(fa_ratios,protection_list,option):
    ###INPUT CHECKING
    default_rp=option
    if fa_ratios is None:
        return None
    
    if default_rp in fa_ratios.index:
        return fa_ratios
            
    flag_stack= False
    if 'rp' in get_list_of_index_names(fa_ratios):
        fa_ratios = fa_ratios.unstack('rp')
        flag_stack = True
 
    if type(protection_list) in [pd.Series, pd.DataFrame]:
        protection_list=protection_list.squeeze().unique().tolist()
        
    #in case of a Multicolumn dataframe, perform this function on each one of the higher level columns
    if type(fa_ratios.columns)==pd.MultiIndex:
        keys = fa_ratios.columns.get_level_values(0).unique()
        return pd.concat({col:interpolate_rps(fa_ratios[col],protection_list,option) for col in  keys}, axis=1).stack('rp')


    ### ACTUAL FUNCTION    
    #figures out all the return periods to be included
    all_rps = list(set(protection_list+fa_ratios.columns.tolist()))
    
    fa_ratios_rps = fa_ratios.copy()
    
    #extrapolates linear towards the 0 return period exposure  (this creates negative exposure that is tackled after interp) (mind the 0 rp when computing probas)
    if len(fa_ratios_rps.columns)==1:
        fa_ratios_rps[0] = fa_ratios_rps.squeeze()
    else:
        fa_ratios_rps[0]=fa_ratios_rps.iloc[:,0]- fa_ratios_rps.columns[0]*(
        fa_ratios_rps.iloc[:,1]-fa_ratios_rps.iloc[:,0])/(
        fa_ratios_rps.columns[1]-fa_ratios_rps.columns[0])
        
    
    #add new, interpolated values for fa_ratios, assuming constant exposure on the right
    x = fa_ratios_rps.columns.values
    y = fa_ratios_rps.values
    fa_ratios_rps= pd.concat(
        [pd.DataFrame(interp1d(x,y,bounds_error=False)(all_rps),index=fa_ratios_rps.index, columns=all_rps)]
        ,axis=1).sort_index(axis=1).clip(lower=0).fillna(method='pad',axis=1)
    fa_ratios_rps.columns.name='rp'

    if flag_stack:
        fa_ratios_rps = fa_ratios_rps.stack('rp')
    
    return fa_ratios_rps    

def agg_to_economy_level (df, seriesname,economy):
    """ aggregates seriesname in df (string of list of string) to economy (country) level using n in df as weight
    does NOT normalize weights to 1."""
    return (df[seriesname].T*df['pcwgt']).T.sum()#level=economy)
	
def agg_to_event_level (df, seriesname,event_level):
    """ aggregates seriesname in df (string of list of string) to event level (country, hazard, rp) across income_cat and affected_cat using n in df as weight
    does NOT normalize weights to 1."""
    return (df[seriesname].T*df['pcwgt']).T.sum(level=event_level)

def calc_delta_welfare(micro, macro,is_revised_dw,study=False):
    # welfare cost from consumption before (c) and after (dc_npv_post) event. Line by line

    #####################################
    # If running in 'study' mode, just load the file from my desktop
    # ^ grab one hh in the poorest quintile, and one in the wealthiest
    temp, c_mean = None, None
    if study == True:
        temp = pd.read_csv('~/Desktop/my_temp.csv',index_col=['Division','hazard','rp'])

        c_mean = temp[['pcwgt','c']].prod(axis=1).sum()/temp['pcwgt'].sum()
        temp['c_mean'] = c_mean
        temp = pd.concat([temp.loc[(temp.quintile==1)].head(2),temp.loc[(temp.quintile==5)].head(2)])

        #temp['dc']/=1.E5
        # ^ uncomment here if we want to make sure that (dw/wprime) converges to dc for small losses among wealthy

    else:
        mac_ix = macro.index.names
        mic_ix = micro.index.names
        temp = pd.merge(micro.reset_index(),macro.reset_index(),on=[i for i in mac_ix]).reset_index().set_index([i for i in mic_ix])
        c_mean = temp[['pcwgt','c']].prod(axis=1).sum()/temp['pcwgt'].sum()

    # Get constants
    h          = 1.E-4
    tmp_rho    = float(temp['rho'].mean())
    tmp_t_reco = float(temp['T_rebuild_K'].mean())/3.
    tmp_ie     = float(temp['income_elast'].mean())

    ######################################
    # For comparison: this is the legacy definition of dw
    temp['w'] = welf1(temp['c']/tmp_rho, tmp_ie, temp['c_5']/tmp_rho)
    temp['dw'] = (welf1(temp['c']/tmp_rho, tmp_ie, temp['c_5']/tmp_rho)
                  - welf1(temp['c']/tmp_rho-temp['dc_npv_post'], tmp_ie,temp['c_5']/tmp_rho))
    temp['wprime'] =(welf(temp['gdp_pc_pp_prov']/tmp_rho+h,tmp_ie)-welf(temp['gdp_pc_pp_prov']/tmp_rho-h,tmp_ie))/(2*h)
    temp['dw_curr'] = temp['dw']/temp['wprime']

    if is_revised_dw == False: 
        print('using legacy calculation of dw')
        temp = temp.reset_index().set_index([i for i in mic_ix])
        return temp['dw']

    ########################################
    # Returns the revised ('rev') definition of dw
    print('using revised calculation of dw')

    # New defintion of w'
    temp['wprime_rev'] = ((c_mean+h)**(1-tmp_ie)-(c_mean-h)**(1-tmp_ie))/(2*h)

    # Set-up to be able to calculate integral
    temp['const'] = ((temp['c']**(1.-temp['income_elast']))/(1.-temp['income_elast']))
    temp['integ'] = 0.

    my_out_x, my_out_yA, my_out_yNA, my_out_yzero = [], [], [], []
    x_min, x_max, n_steps = 0.,10.,1E3
    # ^ make sure that, if T_recon changes, so does x_max!

    int_dt,step_dt = np.linspace(x_min,x_max,num=n_steps,endpoint=True,retstep=True)

    # Calculate integral
    for i_dt in int_dt:
        temp['integ'] += step_dt*(((1.-(temp['dc_post_pds']/temp['c'])*math.e**(-i_dt/tmp_t_reco))**(1-tmp_ie)-1)*math.e**(-tmp_rho*i_dt))

        # If 'study': plot the output
        if study and i_dt < 10:

            aff_val = float((temp['dc_post_pds']/temp['c']).head(1))
            naf_val = float((temp['dc_post_pds']/temp['c']).head(2).tail(1))
            
            tmp_out_yA    = step_dt*(((1.-(aff_val)*math.e**(-i_dt/tmp_t_reco))**(1-tmp_ie)-1)*math.e**(-tmp_rho*i_dt))*float(temp['const'].head(1))
            tmp_out_yNA   = step_dt*(((1.-(naf_val)*math.e**(-i_dt/tmp_t_reco))**(1-tmp_ie)-1)*math.e**(-tmp_rho*i_dt))*float(temp['const'].head(1))
            tmp_out_yzero = step_dt*(((1.-0*math.e**(-i_dt/tmp_t_reco))**(1-tmp_ie)-1)*math.e**(-tmp_rho*i_dt))*float(temp['const'].head(1))
            
            my_out_yA.append(tmp_out_yA)
            my_out_yNA.append(tmp_out_yNA)
            my_out_yzero.append(tmp_out_yzero)
              
            my_out_x.append(i_dt)

    # If 'study': plot the output
    if study:
        ax = plt.gca()
        ltx_str = r'$\Delta W = \frac{c_0^{1-\eta}}{1-\eta}  \int_0^{\infty} [ (1-\frac{\Delta c}{c_0}e^{\frac{-t}{\tau}})^{(1-\eta)}-1 ] \times e^{-\rho t}dt$'
        ax.annotate(ltx_str,xy=(0.25,0.54),xycoords='axes fraction',size=12,va='top',ha='left',annotation_clip=False,zorder=100,weight='bold')
        plt.plot(my_out_x,my_out_yA,color='red',label='Aff. (dc='+str(round(float(temp['dc'].head(1)),1))+')')
        plt.plot(my_out_x,my_out_yNA,color='blue',label='Not aff. (dc='+str(round(float(temp['dc'].head(2).tail(1))*1.E3,2))+'E-3)')
        plt.plot(my_out_x,my_out_yzero,color='black',label='(dc=0)')
        
        leg = ax.legend(loc='upper right',labelspacing=0.75,ncol=1,fontsize=9,borderpad=0.75,fancybox=True,frameon=True,framealpha=0.9)
        leg.get_frame().set_color('white')
        leg.get_frame().set_edgecolor('black')
        leg.get_frame().set_linewidth(0.2)
        
        fig = ax.get_figure()
        fig.savefig('/Users/brian/Desktop/my_plots/dw.pdf',format='pdf')
        
    # 'revised' calculation of dw
    temp['dw_rev'] = temp[['const','integ']].prod(axis=1)
    
    # two alternative definitions of w'
    temp['dw_curr_rev'] = temp['dw_rev']/temp['wprime_rev']
    #temp['dw_curr_rev2'] = temp['dw_rev']/temp['wprime_rev2']

    # Save it out
    if study:     
        temp[['hhid','quintile','affected_cat','rho','income_elast','k','c','c_mean','dk','dc','w','dw','wprime','dw_curr','dw_rev','wprime_rev','dw_curr_rev']].to_csv('~/Desktop/my_dw.csv')
        assert(False)

    temp = temp.reset_index().set_index([i for i in mic_ix])
    return temp['dw_rev']
	
def welf1(c,elast,comp):
    """"Welfare function"""
    y=(c**(1-elast)-1)/(1-elast)
    row1 = c<comp
    row2 = c<=0
    y[row1]=(comp**(1-elast)-1)/(1-elast) + comp**(-elast)*(c-comp)
#    y[row2]=(comp**(1-elast)-1)/(1-elast) + comp**(-elast)*(0-comp)
    return y
	
def welf(c,elast):
    y=(c**(1-elast)-1)/(1-elast)
    return y
	
def average_over_rp(df,default_rp,protection=None):        
    """Aggregation of the outputs over return periods"""    
    if protection is None:
        protection=pd.Series(0,index=df.index)        

    #just drops rp index if df contains default_rp
    if default_rp in df.index.get_level_values('rp'):
        print('default_rp detected, dropping rp')
        return (df.T/protection).T.reset_index('rp',drop=True)
           
    df=df.copy().reset_index('rp')
    protection=protection.copy().reset_index('rp',drop=True)
    
    #computes frequency of each return period
    return_periods=np.unique(df['rp'].dropna())

    proba = pd.Series(np.diff(np.append(1/return_periods,0)[::-1])[::-1],index=return_periods) #removes 0 from the rps 

    #matches return periods and their frequency
    proba_serie=df['rp'].replace(proba).rename('prob')
    proba_serie1 = pd.concat([df.rp,proba_serie],axis=1)
#    print(proba_serie.shape)
#    print(df.rp.shape)
#    print(protection)
    #removes events below the protection level
    proba_serie[protection>df.rp] =0

    #handles cases with multi index and single index (works around pandas limitation)
    idxlevels = list(range(df.index.nlevels))
    if idxlevels==[0]:
        idxlevels =0
#    print(idxlevels)
#    print(get_list_of_index_names(df))
#    print(df.head(10))
    #average weighted by proba
    averaged = df.mul(proba_serie,axis=0).sum(level=idxlevels).drop('rp',axis=1) # frequency times each variables in the columns including rp.
    return averaged,proba_serie1 #here drop rp.
	
	
def average_over_rp1(df,default_rp,protection=None):        
    """Aggregation of the outputs over return periods"""    
    if protection is None:
        protection=pd.Series(0,index=df.index)        

    #just drops rp index if df contains default_rp
    if default_rp in df.index.get_level_values('rp'):
        print('default_rp detected, dropping rp')
        return (df.T/protection).T.reset_index('rp',drop=True)
           
    df=df.copy().reset_index('rp')
    protection=protection.copy().reset_index('rp',drop=True)
    
    #computes frequency of each return period
    return_periods=np.unique(df['rp'].dropna())

    proba = pd.Series(np.diff(np.append(1/return_periods,0)[::-1])[::-1],index=return_periods) #removes 0 from the rps 

    #matches return periods and their frequency
    proba_serie=df['rp'].replace(proba)
#    print(proba_serie.shape)
#    print(df.rp.shape)
#    print(protection)
    #removes events below the protection level
    proba_serie[protection>df.rp] =0

    #handles cases with multi index and single index (works around pandas limitation)
    idxlevels = list(range(df.index.nlevels))
    if idxlevels==[0]:
        idxlevels =0

    #average weighted by proba
    averaged = df.mul(proba_serie,axis=0)#.sum(level=idxlevels) # frequency times each variables in the columns including rp.
    return averaged.drop('rp',axis=1) #here drop rp.

def calc_risk_and_resilience_from_k_w(df, cats_event_iah,economy,is_local_welfare,is_revised_dw): 
    """Computes risk and resilience from dk, dw and protection. Line by line: multiple return periods or hazard is transparent to this function"""
    df=df.copy()    
    ############################
    #Expressing welfare losses in currency 
    #discount rate
    eta = df['income_elast'].mean()
    rho = df['rho']
    h=1e-4

    if is_revised_dw:
        #if is_local_welfare or not is_local_welfare:
        # ^ no dependence on this flag, for now
        c_mean = cats_event_iah[['pcwgt','c']].prod(axis=1).sum()/cats_event_iah['pcwgt'].sum()
        wprime = ((c_mean+h)**(1.-eta)-(c_mean-h)**(1.-eta))/(2*h)

        print('Getting wprime (revised), wprime = '+str(wprime))

    if not is_revised_dw:
        print('Getting wprime (legacy)')
        if is_local_welfare:
            wprime =(welf(df['gdp_pc_pp_prov']/rho+h,df['income_elast'])-welf(df['gdp_pc_pp_prov']/rho-h,df['income_elast']))/(2*h)
        else:
            wprime =(welf(df['gdp_pc_pp_nat']/rho+h,df['income_elast'])-welf(df['gdp_pc_pp_nat']/rho-h,df['income_elast']))/(2*h)
     
    dWref = wprime*df['dK']
    #dWref = wprime*(df['dK']-df['dK_public'])
    # ^ doesn't add in dW from transfers from other provinces...

    #expected welfare loss (per family and total)
    df['wprime'] = wprime
    df['dWref'] = dWref
    df['dWpc_currency'] = df['delta_W']/wprime 
    df['dWtot_currency']=df['dWpc_currency']*cats_event_iah['pcwgt'].sum(level=[economy,'hazard','rp'])#*df['pop']
    
    #Risk to welfare as percentage of local GDP
    df['risk']= df['dWpc_currency']/(df['gdp_pc_pp_prov'])
    
    ############
    #SOCIO-ECONOMIC CAPACITY)
    df['resilience'] =dWref/(df['delta_W'] )

    ############
    #RISK TO ASSETS
    df['risk_to_assets']  =df.resilience*df.risk
    
    return df
