import unittest
from pathlib import Path
import cv2
import numpy as np
from dungeon_farm.minimap import read_minimap,shortest_path,MinimapRoute,XS,YS

PATH=[(0,0),(1,0),(1,1),(2,1),(2,2),(2,3),(1,3),(1,4),(2,4),(3,4)]
EDGES=list(zip(PATH,PATH[1:]))+[((1,0),(2,0)),((2,2),(3,2)),((1,3),(0,3))]


class MinimapTests(unittest.TestCase):
    def test_entire_run_remembers_graph_and_advances_without_clear_time_images(self):
        route=MinimapRoute();reading=read_minimap(self.drawing(),'阿登高地')
        route.confirm('room0',reading,1);route.confirm('room0',reading,2)
        self.assertEqual(route.path,PATH)
        for index,current in enumerate(PATH[:-1]):
            nxt=PATH[index+1];delta=(nxt[0]-current[0],nxt[1]-current[1])
            direction={(1,0):'right',(-1,0):'left',(0,1):'down',(0,-1):'up'}[delta]
            scene='room'+str(index)
            # Closed/absent doors during combat do not damage remembered edges.
            blocked=set(route.blocked)
            self.assertIsNone(route.choose(scene,[],validate_doors=False))
            self.assertEqual(route.blocked,blocked)
            chosen=route.choose(scene,[{'direction':direction}])
            self.assertEqual(chosen['direction'],direction)
            route.enter('room'+str(index+1),direction)
            self.assertEqual(route.current,nxt)
        self.assertEqual(route.status,'at_boss')
        self.assertIsNone(route.choose('room9',[{'direction':'left'}]))

    def test_transient_missing_or_changed_graph_does_not_erase_run_memory(self):
        route=MinimapRoute();reading=read_minimap(self.drawing(),'阿登高地')
        route.confirm('start',reading,1);route.confirm('start',reading,2)
        original=list(route.edges)
        route.enter('fork','right')
        self.assertEqual(route.choose('fork',[{'direction':d} for d in ('left','right','down')])['direction'],'down')
        altered={'current':(1,0),'boss':(3,4),'edges':EDGES+[((2,0),(2,1))]}
        route.confirm('fork',altered,3);route.confirm('fork',altered,4)
        self.assertEqual(route.edges,original)
        self.assertEqual(route.path,PATH[1:])
        route.enter('start','left')
        self.assertEqual(route.current,(0,0))
        self.assertEqual(route.path,PATH)
    def test_route_preconfirmation_overlaps_wave_wait_without_rejecting_locked_doors(self):
        route=MinimapRoute();reading=read_minimap(self.drawing(),'阿登高地')
        self.assertFalse(route.confirm('a',reading,1))
        self.assertTrue(route.confirm('a',reading,1.2))
        self.assertEqual(route.blocked,set())
        self.assertEqual(route.choose('a',[{'direction':'right'}],reading,1.2)['direction'],'right')
    def drawing(self,current=(0,0)):
        frame=np.zeros((480,640,3),dtype=np.uint8)
        rooms={tuple(n) for e in EDGES for n in e}
        for col,row in rooms:
            x,y=XS[col],YS[row];frame[y-5:y+6,x-5:x+6]=(70,25,5)
        for a,b in EDGES:
            cv2.line(frame,(XS[a[0]],YS[a[1]]),(XS[b[0]],YS[b[1]]),(130,100,60),3)
        frame[YS[4]-2:YS[4]+3,XS[3]-2:XS[3]+3]=(20,50,200)
        x,y=XS[current[0]],YS[current[1]];frame[y-1:y+2,x:x+2]=(220,150,40)
        return frame

    def test_full_graph_routes_around_walls_and_skips_dead_ends(self):
        result=read_minimap(self.drawing(),'阿登高地')
        self.assertIsNotNone(result)
        self.assertEqual(result['path'],PATH)
        self.assertNotIn([(2,3),(2,4)],result['edges'])

    def test_missing_or_ambiguous_player_does_not_guess(self):
        self.assertIsNone(read_minimap(np.zeros((480,640,3),np.uint8),'阿登高地'))
        frame=self.drawing();frame[57:60,598:600]=(220,150,40)
        self.assertIsNone(read_minimap(frame,'阿登高地'))
        self.assertIsNone(read_minimap(self.drawing(),'根特东门'))

    def test_red_scenery_under_fog_does_not_create_second_boss(self):
        frame=self.drawing((2,4))
        x,y=XS[1],YS[2];frame[y-3:y+4,x-3:x+4]=(10,40,180)
        result=read_minimap(frame,'阿登高地')
        self.assertEqual(result['boss'],(3,4))
        self.assertNotIn((1,2),result['rooms'])
        self.assertEqual(result['path'],[(2,4),(3,4)])

    def test_new_run_fog_uses_verified_layout_without_waiting_for_full_map(self):
        frame=self.drawing()
        frame[35:110,575:640]=0
        for tile in ((0,0),(1,0)):
            x,y=XS[tile[0]],YS[tile[1]];frame[y-5:y+6,x-5:x+6]=(70,25,5)
        frame[YS[0]-1:YS[0]+2,XS[0]:XS[0]+2]=(220,150,40)
        frame[YS[4]-2:YS[4]+3,XS[3]-2:XS[3]+3]=(20,50,200)
        result=read_minimap(frame,'阿登高地')
        self.assertEqual(result['source'],'verified_layout_under_fog')
        self.assertEqual(result['path'],PATH)

    def test_two_fresh_confirmations_and_room_change_reset(self):
        route=MinimapRoute();reading=read_minimap(self.drawing((1,0)),'阿登高地')
        doors=[{'direction':'left'},{'direction':'right'},{'direction':'down'}]
        self.assertIsNone(route.choose('a',doors,reading,1))
        self.assertIsNone(route.choose('a',doors,reading,1))
        self.assertEqual(route.choose('a',doors,reading,2)['direction'],'down')
        self.assertIsNone(route.choose('b',doors,reading,2))

    def test_missing_local_door_never_forces_nonexistent_shortcut(self):
        route=MinimapRoute();reading=read_minimap(self.drawing((2,4)),'阿登高地')
        route.choose('a',[{'direction':'left'}],reading,1)
        self.assertIsNone(route.choose('a',[{'direction':'left'}],reading,2))
        self.assertEqual(route.status,'no_path')

    def test_at_boss_never_backtracks_to_a_used_room(self):
        route=MinimapRoute();reading={'current':(3,4),'boss':(3,4),'edges':EDGES}
        route.choose('boss',[{'direction':'left'}],reading,1)
        self.assertIsNone(route.choose('boss',[{'direction':'left'}],reading,2))
        self.assertEqual(route.status,'at_boss')

    def test_rejected_connection_stays_rejected_when_returning_to_fork(self):
        route=MinimapRoute();edges=EDGES+[((2,0),(2,1))]
        dead={'current':(2,0),'boss':(3,4),'edges':edges}
        route.choose('dead',[{'direction':'left'}],dead,1)
        self.assertEqual(route.choose('dead',[{'direction':'left'}],dead,2)['direction'],'left')
        fork={'current':(1,0),'boss':(3,4),'edges':edges}
        doors=[{'direction':d} for d in ('left','right','down')]
        route.choose('fork',doors,fork,3)
        self.assertEqual(route.choose('fork',doors,fork,4)['direction'],'down')

    @unittest.skipUnless((Path(__file__).parent/'fixtures/arden-dead-end.png').exists(),'本机截图不随安装包发布')
    def test_translucent_wall_is_not_a_connection(self):
        frame=cv2.resize(cv2.imread(str(Path(__file__).parent/'fixtures/arden-dead-end.png')),(640,480))
        result=read_minimap(frame,'阿登高地')
        self.assertEqual(result['current'],(2,0))
        self.assertNotIn([(2,0),(2,1)],result['edges'])
        self.assertEqual(result['path'][1:3],[(1,0),(1,1)])

    @unittest.skipUnless((Path(__file__).parent/'fixtures/arden-start.png').exists(),'本机截图不随安装包发布')
    def test_observed_start_screen(self):
        frame=cv2.resize(cv2.imread(str(Path(__file__).parent/'fixtures/arden-start.png')),(640,480))
        result=read_minimap(frame,'阿登高地')
        self.assertEqual(result['current'],(0,0));self.assertEqual(result['boss'],(3,4))
        self.assertEqual(result['path'],PATH)

    @unittest.skipUnless((Path(__file__).parent/'fixtures/arden-fog.png').exists(),'本机截图不随安装包发布')
    def test_observed_new_run_fog_screen(self):
        frame=cv2.resize(cv2.imread(str(Path(__file__).parent/'fixtures/arden-fog.png')),(640,480))
        result=read_minimap(frame,'阿登高地')
        self.assertEqual(result['current'],(0,0))
        self.assertEqual(result['source'],'verified_layout_under_fog')
        self.assertEqual(result['path'],PATH)
